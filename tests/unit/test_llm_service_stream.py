import logging
from collections.abc import AsyncGenerator

import pytest

from app.schemas.estimation import EstimateResponse
from app.schemas.stream import PartialEvent, StatusEvent
from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from app.services.providers.base import ProviderSwitch, StreamEvent, T
from tests.factories import make_service, request
from tests.fakes import FakeProvider, SlowFakeProvider


async def test_stream_yields_status_partials_then_result(
    service_with_fake: EstimationService,
) -> None:
    items = [i async for i in service_with_fake.estimate_stream(request())]
    assert isinstance(items[0], StatusEvent) and items[0].phase == "calling_llm"
    partials = [i for i in items if isinstance(i, PartialEvent)]
    assert partials and [p.seq for p in partials] == sorted({p.seq for p in partials})
    assert isinstance(items[-1], EstimateResponse)
    assert items[-1].metrics.ttft_ms is not None
    assert sum(isinstance(i, EstimateResponse) for i in items) == 1


async def test_closing_the_stream_early_closes_the_provider_stream(
    service_with_slow_fake: EstimationService,
    slow_fake: SlowFakeProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    gen = service_with_slow_fake.estimate_stream(request())
    await anext(gen)  # status
    await anext(gen)  # first partial
    with caplog.at_level(logging.INFO, logger="app.llm"):
        await gen.aclose()
    assert slow_fake.closed_streams == 1
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "cancelled"


async def test_leaving_after_the_upstream_finished_still_logs_the_call_once(
    service_with_fake: EstimationService, caplog: pytest.LogCaptureFixture
) -> None:
    gen = service_with_fake.estimate_stream(request())
    with caplog.at_level(logging.INFO, logger="app.llm"):
        async for item in gen:
            if isinstance(item, StatusEvent) and item.phase == "validating":
                break
        await gen.aclose()
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "ok"


async def test_provider_error_propagates_as_llm_error(
    service_with_failing_fake: EstimationService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.llm"), pytest.raises(UpstreamUnavailable):
        [i async for i in service_with_failing_fake.estimate_stream(request())]
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "upstream_unavailable" and record.fields["stream"] is True


async def test_stream_logs_one_call_with_stream_fields(caplog: pytest.LogCaptureFixture) -> None:
    service = make_service(FakeProvider(model="gpt-4o-mini"))
    with caplog.at_level(logging.INFO, logger="app.llm"):
        items = [i async for i in service.estimate_stream(request())]
    response = items[-1]
    assert isinstance(response, EstimateResponse)
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    fields = record.fields
    assert (fields["outcome"], fields["stream"], fields["cache"]) == ("ok", True, "bypass")
    assert fields["ttft_ms"] == response.metrics.ttft_ms
    assert response.metrics.cost_usd is not None
    assert fields["cost_usd"] == response.metrics.cost_usd
    assert (fields["attempt"], fields["fallback"]) == (1, False)


class SwitchingFake(FakeProvider):
    """Announces a switch to the fallback before the first delta, as the router does."""

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        yield ProviderSwitch(provider="anthropic", model="claude-haiku-4-5", cause="timeout")
        async for event in super().stream(
            system=system, user=user, schema=schema, cache_key=cache_key
        ):
            yield event


async def test_provider_switch_becomes_a_fallback_status() -> None:
    items = [i async for i in make_service(SwitchingFake()).estimate_stream(request())]
    statuses = [i for i in items if isinstance(i, StatusEvent)]
    assert [s.phase for s in statuses] == ["calling_llm", "fallback", "validating"]
    assert (statuses[1].provider, statuses[1].model) == ("anthropic", "claude-haiku-4-5")


async def test_both_paths_send_the_same_prompt_cache_key(fake: FakeProvider) -> None:
    service = make_service(fake)
    await service.estimate(request())
    [_ async for _ in service.estimate_stream(request())]
    assert [c["cache_key"] for c in fake.calls] == [service.prompt_cache_key] * 2
