import asyncio
import logging
import time
from collections.abc import AsyncIterator

import fakeredis
import pytest

from app.schemas.estimation import EstimateResponse
from app.schemas.stream import StatusEvent
from app.services.cache import RedisCache
from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from tests.factories import breakdown, make_service, request
from tests.fakes import FakeProvider


def records(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [r.fields for r in caplog.records if r.getMessage() == event]


async def test_second_identical_request_is_served_from_cache(
    service_with_fakeredis: EstimationService, fake: FakeProvider
) -> None:
    first = await service_with_fakeredis.estimate(request())
    second = await service_with_fakeredis.estimate(request())
    assert len(fake.calls) == 1
    assert first.metrics.cache_hit is False and second.metrics.cache_hit is True
    assert second.metrics.cost_usd == 0 and second.metrics.attempts == 0


async def test_stream_cache_hit_emits_status_then_result(
    service_with_fakeredis: EstimationService,
) -> None:
    await service_with_fakeredis.estimate(request())
    items = [i async for i in service_with_fakeredis.estimate_stream(request())]
    assert [type(i).__name__ for i in items] == ["StatusEvent", "EstimateResponse"]
    assert items[0].phase == "cache_hit"


async def test_failures_are_not_cached(
    service_with_fakeredis_failing: EstimationService, redis_client: fakeredis.FakeAsyncRedis
) -> None:
    with pytest.raises(UpstreamUnavailable):
        await service_with_fakeredis_failing.estimate(request())
    assert await redis_client.keys("estimate:*") == []


async def test_cancelled_stream_is_not_cached(
    service_with_fakeredis_slow: EstimationService, redis_client: fakeredis.FakeAsyncRedis
) -> None:
    gen = service_with_fakeredis_slow.estimate_stream(request())
    await anext(gen)  # status
    await anext(gen)  # first partial
    await gen.aclose()
    assert await redis_client.keys("estimate:*") == []


async def test_a_hit_reports_this_requests_metrics_and_logs_no_llm_call(
    service_with_fakeredis: EstimationService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.llm"):
        first = await service_with_fakeredis.estimate(request())
        second = await service_with_fakeredis.estimate(request())
    [call] = records(caplog, "llm_call")
    assert call["cache"] == "miss"
    [hit] = records(caplog, "estimate_cache_hit")
    assert (hit["cache"], hit["stream"], hit["prompt_version"]) == ("hit", False, "v1")
    assert hit["latency_ms"] == second.metrics.latency_ms
    assert (second.metrics.ttft_ms, second.metrics.fallback_used) == (None, False)
    assert second.model_dump(exclude={"metrics"}) == first.model_dump(exclude={"metrics"})


async def test_refresh_skips_the_lookup_and_overwrites_the_entry(
    service_with_fakeredis: EstimationService,
    fake: FakeProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await service_with_fakeredis.estimate(request())
    fake.result = breakdown(project_name="Regenerated")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        fresh = await service_with_fakeredis.estimate(request(), refresh=True)
    assert len(fake.calls) == 2 and fresh.metrics.cache_hit is False
    [call] = records(caplog, "llm_call")
    assert call["cache"] == "bypass"
    again = await service_with_fakeredis.estimate(request())
    assert again.metrics.cache_hit is True and again.breakdown.project_name == "Regenerated"
    assert len(fake.calls) == 2


async def test_a_completed_stream_is_cached(
    service_with_fakeredis: EstimationService, fake: FakeProvider
) -> None:
    [_ async for _ in service_with_fakeredis.estimate_stream(request())]
    second = [i async for i in service_with_fakeredis.estimate_stream(request())][-1]
    assert isinstance(second, EstimateResponse) and second.metrics.cache_hit is True
    assert len(fake.calls) == 1


async def test_leaving_during_the_trailing_events_caches_nothing(
    service_with_fakeredis: EstimationService,
    redis_client: fakeredis.FakeAsyncRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The upstream call is complete, but the client never got the result.
    gen = service_with_fakeredis.estimate_stream(request())
    with caplog.at_level(logging.INFO, logger="app.llm"):
        async for item in gen:
            if isinstance(item, StatusEvent) and item.phase == "validating":
                break
        await gen.aclose()
    assert await redis_client.keys("estimate:*") == []
    [call] = records(caplog, "llm_call")
    assert (call["outcome"], call["cache"]) == ("ok", "miss")


@pytest.mark.parametrize("stream", [False, True])
async def test_redis_down_serves_the_request_and_logs_cache_error(
    stream: bool, caplog: pytest.LogCaptureFixture
) -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    cache = RedisCache(
        fakeredis.FakeAsyncRedis(server=server, decode_responses=True), ttl_seconds=60
    )
    service = make_service(FakeProvider(), cache)
    with caplog.at_level(logging.INFO, logger="app.llm"):
        if stream:
            response = [i async for i in service.estimate_stream(request())][-1]
        else:
            response = await service.estimate(request())
    assert isinstance(response, EstimateResponse) and response.metrics.cache_hit is False
    [call] = records(caplog, "llm_call")
    assert (call["outcome"], call["cache"], call["stream"]) == ("ok", "error", stream)


@pytest.fixture
async def silent_redis_url() -> AsyncIterator[str]:
    """Accepts connections and never answers: a hung or blackholed Redis."""

    async def hang(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.Event().wait()

    server = await asyncio.start_server(hang, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    yield f"redis://{host}:{port}/0"
    server.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_a_slow_but_alive_redis_adds_at_most_half_a_second(
    stream: bool, slow_redis_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    # A new connection: four 0.1 s replies before the GET's, none slow enough for a socket
    # timeout. Unbounded, the lookup would be a miss after 0.5 s.
    cache = RedisCache.from_url(slow_redis_url, ttl_seconds=60)
    service = make_service(FakeProvider(), cache)
    started = time.perf_counter()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        if stream:
            items = service.estimate_stream(request())
            first = await anext(items)
            first_at = time.perf_counter() - started
            response = [first, *[i async for i in items]][-1]
        else:
            response = await service.estimate(request())
    elapsed = time.perf_counter() - started
    await cache.aclose()
    assert isinstance(response, EstimateResponse)
    assert elapsed <= 0.5
    if stream:
        assert first_at <= 0.25
    [call] = records(caplog, "llm_call")
    assert call["cache"] == "error"


@pytest.mark.parametrize("stream", [False, True])
async def test_a_hung_redis_adds_at_most_half_a_second(
    stream: bool, silent_redis_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    cache = RedisCache.from_url(silent_redis_url, ttl_seconds=60)
    service = make_service(FakeProvider(), cache)
    started = time.perf_counter()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        if stream:
            response = [i async for i in service.estimate_stream(request())][-1]
        else:
            response = await service.estimate(request())
    elapsed = time.perf_counter() - started
    await cache.aclose()
    assert isinstance(response, EstimateResponse)
    assert elapsed <= 0.5
    [call] = records(caplog, "llm_call")
    assert call["cache"] == "error"
