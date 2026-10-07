"""Exact-match response cache. Fail-open: Redis down or slow costs a miss, never a request."""

import hashlib
import json
import logging
from typing import Literal, Protocol

import anyio
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.config import Settings
from app.schemas.estimation import EstimateResponse

logger = logging.getLogger(__name__)

CACHE_SCHEMA = 1  # bump when the stored EstimateResponse shape changes
# Wall-clock bound on each whole get/set, connection handshake included (a new redis-py
# connection makes three round trips before the command: HELLO, CLIENT MAINT_NOTIFICATIONS, then
# two pipelined CLIENT SETINFO), so Redis adds at most ~0.4 s a request.
TIMEOUT_SECONDS = 0.2

type CacheStatus = Literal["hit", "miss", "error", "bypass"]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_scope(settings: Settings) -> str:
    """Everything outside the prompt that shapes the stored response: who may serve it, how, and
    the rate and capacity baked into its totals and markdown."""
    return canonical_json(
        {
            "chain": [f"{provider}:{model}" for provider, model in settings.chain],
            "temperature": settings.llm_temperature,
            "effort": settings.llm_reasoning_effort,
            "max_output_tokens": settings.llm_max_output_tokens,
            "hourly_rate": settings.blended_hourly_rate,
            "weekly_capacity_hours": settings.weekly_capacity_hours,
        }
    )


def cache_key(*, prompt_version: str, system: str, user: str, scope: str, schema_name: str) -> str:
    prompt_sha256 = hashlib.sha256(canonical_json([system, user]).encode()).hexdigest()
    payload = {
        "cache_schema": CACHE_SCHEMA,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "scope": scope,
        "output_schema": schema_name,
    }
    return f"estimate:{hashlib.sha256(canonical_json(payload).encode()).hexdigest()}"


class ResponseCache(Protocol):
    async def get(self, key: str) -> tuple[EstimateResponse | None, CacheStatus]: ...
    async def set(self, key: str, value: EstimateResponse) -> None: ...
    async def aclose(self) -> None: ...


class NullCache:
    """No `REDIS_URL`: every lookup is a bypass and every write a no-op."""

    async def get(self, key: str) -> tuple[EstimateResponse | None, CacheStatus]:
        return None, "bypass"

    async def set(self, key: str, value: EstimateResponse) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _log_error(op: str, exc: Exception) -> None:
    # The class only: messages name hosts, and keys derive from the transcript.
    logger.warning("cache_error", extra={"fields": {"op": op, "error": type(exc).__name__}})


class RedisCache:
    def __init__(self, client: Redis, *, ttl_seconds: int) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int) -> "RedisCache":
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=TIMEOUT_SECONDS,
            socket_timeout=TIMEOUT_SECONDS,
            retry=Retry(NoBackoff(), retries=0),
        )
        return cls(client, ttl_seconds=ttl_seconds)

    async def get(self, key: str) -> tuple[EstimateResponse | None, CacheStatus]:
        try:
            with anyio.fail_after(TIMEOUT_SECONDS):
                value = await self.client.get(key)
        except (RedisError, TimeoutError) as exc:  # TimeoutError: the wall-clock bound
            _log_error("get", exc)
            return None, "error"
        if not isinstance(value, str):
            return None, "miss"
        try:
            return EstimateResponse.model_validate_json(value), "hit"
        except ValidationError:  # invalid JSON too
            logger.warning("cache_stale")
            return None, "miss"

    async def set(self, key: str, value: EstimateResponse) -> None:
        try:
            with anyio.fail_after(TIMEOUT_SECONDS):
                await self.client.set(key, value.model_dump_json(), ex=self.ttl_seconds)
        except (RedisError, TimeoutError) as exc:
            _log_error("set", exc)

    async def aclose(self) -> None:
        await self.client.aclose()


def build_cache(settings: Settings) -> ResponseCache:
    if not settings.redis_url:
        return NullCache()
    return RedisCache.from_url(
        settings.redis_url.get_secret_value(), ttl_seconds=settings.cache_ttl_seconds
    )
