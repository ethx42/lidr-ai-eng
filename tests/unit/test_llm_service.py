import logging
from dataclasses import replace

import pytest

from app.prompts.loader import DEFAULT_VERSION, render_estimation_prompt
from app.schemas.estimation import Usage
from app.services.cache import NullCache
from app.services.errors import (
    Attempt,
    InvalidModelOutput,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider, LLMResult, T
from app.services.providers.fallback import Cooldown, FallbackProvider
from tests.factories import TRANSCRIPT, breakdown, request, typed_request
from tests.fakes import FakeProvider


def service(provider: LLMProvider, rate: float | None = None) -> EstimationService:
    return EstimationService(
        provider=provider,
        prompt_version=DEFAULT_VERSION,
        weekly_capacity_hours=30,
        hourly_rate=rate,
        cache=NullCache(),
        cache_scope="",
    )


async def test_estimate_pipeline() -> None:
    provider = FakeProvider()
    request = typed_request(TRANSCRIPT, output_language="Spanish")
    response = await service(provider, rate=100).estimate(request)
    assert response.breakdown.totals.expected_hours == 41.0
    assert response.breakdown.totals.estimated_cost == 4100.0
    assert "**Total estimated: 41.0 hours**" in response.estimation
    assert response.grounding.score == 1.0
    assert response.prompt_version == "v1"
    assert (response.provider, response.model) == ("openai", "fake-model")
    assert response.usage.cached_input_tokens == 1024
    [call] = provider.calls
    assert (call["system"], call["user"]) == render_estimation_prompt(request)
    assert TRANSCRIPT in call["user"]
    assert "<output_language>Spanish</output_language>" in call["user"]


async def test_system_prompt_identical_across_requests() -> None:
    provider = FakeProvider()
    svc = service(provider)
    await svc.estimate(typed_request("Client: one", output_language="English"))
    await svc.estimate(typed_request("Client: two"))
    assert provider.calls[0]["system"] == provider.calls[1]["system"]
    assert "Client: one" not in provider.calls[0]["system"]


@pytest.mark.usefixtures("prompts_v99")
async def test_cache_key_follows_prompt_version() -> None:
    provider = FakeProvider()
    request = typed_request("Client: one")
    await service(provider).estimate(request)
    await service(provider).estimate(request)
    await EstimationService(
        provider=provider,
        prompt_version="v99",
        weekly_capacity_hours=30,
        hourly_rate=None,
        cache=NullCache(),
        cache_scope="",
    ).estimate(request)
    keys = [call["cache_key"] for call in provider.calls]
    assert keys[0] == keys[1] == "estimator-v1"
    assert keys[2] == "estimator-v99"


async def test_grounding_flags_fabricated_requirement() -> None:
    fabricated = breakdown(
        requirements=[
            {"id": "R1", "statement": "Booking", "evidence": "a booking app"},
            {"id": "R2", "statement": "Loyalty", "evidence": "a loyalty program"},
        ]
    )
    response = await service(FakeProvider(result=fabricated)).estimate(typed_request(TRANSCRIPT))
    assert response.grounding.ungrounded_requirement_ids == ["R2"]
    assert "⚠ **R2**" in response.estimation


async def test_llm_call_logged_without_transcript(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        await service(FakeProvider()).estimate(typed_request(TRANSCRIPT))
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "ok"  # type: ignore[attr-defined]
    assert record.fields["input_tokens"] == 1200  # type: ignore[attr-defined]
    assert {"cause", "upstream_status"}.isdisjoint(record.fields)  # type: ignore[attr-defined]
    for r in caplog.records:
        assert "yoga studio" not in str(r.__dict__)


async def test_provider_error_logged_and_raised(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), pytest.raises(UpstreamUnavailable):
        await service(FakeProvider(error=UpstreamUnavailable())).estimate(typed_request(TRANSCRIPT))
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "upstream_unavailable"  # type: ignore[attr-defined]


# A Haiku answer cut at max_tokens: billed, so logged with its tokens and their cost.
BILLED = Usage(input_tokens=6500, output_tokens=4096)


@pytest.mark.parametrize(
    "usage,tokens,cost",
    [(BILLED, (6500, 4096), pytest.approx(0.02698)), (None, (0, 0), None)],
    ids=["reported", "unknown"],
)
async def test_a_failed_call_logs_the_usage_the_provider_reported(
    usage: Usage | None, tokens: tuple[int, int], cost: object, caplog: pytest.LogCaptureFixture
) -> None:
    error = InvalidModelOutput(reason="stop_reason:max_tokens", usage=usage)
    provider = FakeProvider(error=error, name="anthropic", model="claude-haiku-4-5")
    with caplog.at_level(logging.INFO), pytest.raises(InvalidModelOutput):
        await service(provider).estimate(request())
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    fields = record.fields  # type: ignore[attr-defined]
    assert (fields["input_tokens"], fields["output_tokens"]) == tokens
    assert fields["cost_usd"] == cost


async def test_blocking_response_carries_metrics(service_with_fake: EstimationService) -> None:
    response = await service_with_fake.estimate(request())
    assert response.metrics.cache_hit is False
    assert response.metrics.attempts == 1
    assert response.metrics.ttft_ms is None
    assert response.provider == "openai" and response.model == "fake-model"


class ServedByFallback(FakeProvider):
    """Configured as openai/fake-model; the result comes from the fallback, as Task 14 does."""

    def _result(self, schema: type[T]) -> LLMResult[T]:
        served = super()._result(schema)
        return replace(
            served, provider="anthropic", model="claude-haiku-4-5", attempts=2, fallback_used=True
        )


async def test_response_reports_the_provider_that_served(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        response = await service(ServedByFallback()).estimate(request())
    assert (response.provider, response.model) == ("anthropic", "claude-haiku-4-5")
    assert response.metrics.latency_ms == 42
    # Haiku 4.5: 1024 cached * 0.10 + 176 written * 1.25 + 800 out * 5.00 (per 1M tokens)
    assert response.metrics.cost_usd == pytest.approx(0.004322)
    assert (response.metrics.attempts, response.metrics.fallback_used) == (2, True)
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    fields = record.fields  # type: ignore[attr-defined]
    assert (fields["provider"], fields["model"]) == ("anthropic", "claude-haiku-4-5")


def logged(caplog: pytest.LogCaptureFixture) -> list[tuple[str, tuple[object, ...]]]:
    keys = ("provider", "model", "attempt", "fallback", "stream", "prompt_version", "outcome")
    return [
        (r.getMessage(), tuple(r.fields.get(k) for k in keys))
        for r in caplog.records
        if r.name == "app.llm"
    ]


async def test_a_fallback_logs_one_record_per_attempt(caplog: pytest.LogCaptureFixture) -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), model="gpt-4o-mini")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    with caplog.at_level(logging.INFO):
        await service(FallbackProvider([primary, secondary], Cooldown())).estimate(request())
    assert logged(caplog) == [
        ("llm_fallback", ("openai", "gpt-4o-mini", 1, False, False, "v1", "upstream_unavailable")),
        ("llm_call", ("anthropic", "claude-haiku-4-5", 2, True, False, "v1", "ok")),
    ]


async def test_an_error_after_a_fallback_logs_the_attempt_that_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), model="gpt-4o-mini")
    secondary = FakeProvider(
        name="anthropic", model="claude-haiku-4-5", error=InvalidModelOutput(reason="refusal")
    )
    router = FallbackProvider([primary, secondary], Cooldown())
    with caplog.at_level(logging.INFO), pytest.raises(InvalidModelOutput):
        await service(router).estimate(request())
    assert logged(caplog)[-1] == (
        "llm_call",
        ("anthropic", "claude-haiku-4-5", 2, True, False, "v1", "invalid_model_output"),
    )


async def test_a_failing_fallback_after_a_cooldown_skip_reports_attempt_1(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), model="gpt-4o-mini")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    estimator = service(FallbackProvider([primary, secondary], Cooldown(failures=1)))
    await estimator.estimate(request())  # the primary fails once and cools down
    secondary.error = UpstreamRateLimited()
    caplog.clear()
    with caplog.at_level(logging.INFO), pytest.raises(UpstreamRateLimited) as info:
        await estimator.estimate(request())
    assert len(primary.calls) == 1
    assert info.value.attempt == Attempt("anthropic", "claude-haiku-4-5", 1, fallback=True)
    assert logged(caplog) == [
        (
            "llm_call",
            ("anthropic", "claude-haiku-4-5", 1, True, False, "v1", "upstream_rate_limited"),
        ),
    ]
