import logging
import time
from typing import Any

import fakeredis
import pytest

from app.config import Settings
from app.services import cache as cache_module
from app.services.cache import (
    TIMEOUT_SECONDS,
    NullCache,
    RedisCache,
    build_cache,
    cache_key,
    cache_scope,
)
from tests.factories import response_fixture


async def test_round_trip_with_ttl() -> None:
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    cache = RedisCache(client, ttl_seconds=60)
    assert await cache.get("estimate:abc") == (None, "miss")
    await cache.set("estimate:abc", response_fixture())
    assert await cache.get("estimate:abc") == (response_fixture(), "hit")
    assert 0 < await client.ttl("estimate:abc") <= 60


async def test_outage_is_a_miss_not_an_error(caplog: pytest.LogCaptureFixture) -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    cache = RedisCache(
        fakeredis.FakeAsyncRedis(server=server, decode_responses=True), ttl_seconds=60
    )
    assert await cache.get("estimate:x") == (None, "error")
    await cache.set("estimate:x", response_fixture())  # no exception
    assert "cache_error" in caplog.text  # logged at WARNING


async def test_cache_errors_name_the_operation_and_class_never_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    cache = RedisCache(
        fakeredis.FakeAsyncRedis(server=server, decode_responses=True), ttl_seconds=60
    )
    with caplog.at_level(logging.WARNING, logger="app.services.cache"):
        await cache.get("estimate:secret-key")
        await cache.set("estimate:secret-key", response_fixture())
    records = [r for r in caplog.records if r.getMessage() == "cache_error"]
    assert [(r.levelno, r.fields["op"], r.fields["error"]) for r in records] == [
        (logging.WARNING, "get", "ConnectionError"),
        (logging.WARNING, "set", "ConnectionError"),
    ]
    assert "secret-key" not in caplog.text
    assert all("secret-key" not in str(r.__dict__) for r in records)


async def test_stale_or_corrupt_entry_is_a_miss() -> None:
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    await client.set("estimate:x", '{"not": "a response"}')
    assert await RedisCache(client, ttl_seconds=60).get("estimate:x") == (None, "miss")


async def test_invalid_json_is_a_logged_miss(caplog: pytest.LogCaptureFixture) -> None:
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    await client.set("estimate:x", '{"estimation": "trunc')
    with caplog.at_level(logging.WARNING, logger="app.services.cache"):
        assert await RedisCache(client, ttl_seconds=60).get("estimate:x") == (None, "miss")
    assert [r.getMessage() for r in caplog.records if r.name == "app.services.cache"] == [
        "cache_stale"
    ]


def test_key_changes_with_every_input() -> None:
    base = {
        "prompt_version": "v4",
        "system": "S",
        "user": "U",
        "scope": "openai:gpt-4o-mini|t=0.2",
        "schema_name": "EstimationBreakdown",
    }
    keys = {cache_key(**base)} | {cache_key(**(base | {k: base[k] + "x"})) for k in base}
    assert len(keys) == 1 + len(base)
    assert cache_key(**base).startswith("estimate:")


def test_key_keeps_system_and_user_apart() -> None:
    common = {"prompt_version": "v4", "scope": "s", "schema_name": "EstimationBreakdown"}
    assert cache_key(system="ab", user="c", **common) != cache_key(system="a", user="bc", **common)


def settings(**values: Any) -> Settings:
    base = {"openai_api_key": "k", "anthropic_api_key": "k", "llm_fallbacks": ""}
    return Settings(_env_file=None, **(base | values))


def test_scope_changes_with_chain_and_generation_params() -> None:
    variants = [
        settings(),
        settings(llm_model="gpt-4o"),
        settings(llm_fallbacks="anthropic:claude-haiku-4-5"),
        settings(llm_temperature=0.3),
        settings(llm_reasoning_effort="low"),
        settings(llm_max_output_tokens=2048),
        settings(blended_hourly_rate=95),
        settings(weekly_capacity_hours=20),
    ]
    assert len({cache_scope(s) for s in variants}) == len(variants)
    assert cache_scope(settings()) == cache_scope(settings())


async def test_null_cache_bypasses() -> None:
    cache = NullCache()
    await cache.set("estimate:x", response_fixture())
    assert await cache.get("estimate:x") == (None, "bypass")


async def test_redis_url_selects_the_cache() -> None:
    assert isinstance(build_cache(settings()), NullCache)
    configured = settings(redis_url="redis://:hunter2@localhost:6379/0", cache_ttl_seconds=60)
    assert "hunter2" not in repr(configured)
    cache = build_cache(configured)
    assert isinstance(cache, RedisCache) and cache.ttl_seconds == 60
    pool = cache.client.connection_pool
    assert pool.connection_kwargs["password"] == "hunter2"
    timeouts = (
        pool.connection_kwargs["socket_connect_timeout"],
        pool.connection_kwargs["socket_timeout"],
    )
    assert timeouts == (0.2, 0.2)
    assert pool.make_connection().retry.get_retries() == 0
    await cache.aclose()


async def test_a_slow_redis_is_cut_off_per_call(
    slow_redis_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No socket timeout can fire (each reply takes 0.1 s), yet a new connection needs 0.5 s: the
    # call must be cut by the wall-clock bound, whose builtin TimeoutError redis-py never raises.
    caught: list[type[Exception]] = []
    log_error = cache_module._log_error

    def spy(op: str, exc: Exception) -> None:
        caught.append(type(exc))
        log_error(op, exc)

    monkeypatch.setattr(cache_module, "_log_error", spy)
    cache = RedisCache.from_url(slow_redis_url, ttl_seconds=60)
    with caplog.at_level(logging.WARNING, logger="app.services.cache"):
        started = time.perf_counter()
        assert await cache.get("estimate:x") == (None, "error")
        got_at = time.perf_counter()
        await cache.set("estimate:x", response_fixture())
        set_at = time.perf_counter()
    await cache.aclose()
    for elapsed in (got_at - started, set_at - got_at):  # two calls stay under 0.5 s
        assert TIMEOUT_SECONDS - 0.01 <= elapsed < 0.25
    assert caught == [TimeoutError, TimeoutError]  # builtin, not redis.exceptions.TimeoutError
    errors = [r.fields for r in caplog.records if r.getMessage() == "cache_error"]
    assert errors == [
        {"op": "get", "error": "TimeoutError"},
        {"op": "set", "error": "TimeoutError"},
    ]
