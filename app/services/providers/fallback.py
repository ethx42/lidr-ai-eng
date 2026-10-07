"""Fallback router: tries the chain in order, skipping providers in cooldown, and moves on only
after an availability failure; when streaming, only before the first delta (no mixed answers)."""

import time
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import AsyncExitStack, aclosing
from dataclasses import dataclass, field, replace

from app.config import Provider
from app.observability import llm_logger, prompt_version_var
from app.services.errors import (
    QUOTA,
    Attempt,
    LLMError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResult,
    ProviderSwitch,
    StreamEvent,
    T,
    TextDelta,
)


@dataclass
class Cooldown:
    """In-process: `failures` consecutive availability failures bench a key for `seconds`."""

    failures: int = 3
    seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _streaks: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _benched_until: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def available(self, key: str) -> bool:
        return self.clock() >= self._benched_until.get(key, float("-inf"))

    def record_failure(self, key: str) -> None:
        # Only a success ends the streak, so one more failure after the cooldown benches it again.
        self._streaks[key] = self._streaks.get(key, 0) + 1
        if self._streaks[key] >= self.failures:
            self._benched_until[key] = self.clock() + self.seconds

    def record_success(self, key: str) -> None:
        self._streaks.pop(key, None)
        self._benched_until.pop(key, None)


def falls_back(exc: LLMError) -> bool:
    return isinstance(exc, UpstreamUnavailable | UpstreamRateLimited) or exc.reason == QUOTA


def _key(provider: LLMProvider) -> str:
    return f"{provider.name}:{provider.model}"


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class FallbackProvider:
    """An `LLMProvider` over a chain; reports the primary's name and model."""

    def __init__(self, chain: Sequence[LLMProvider], cooldown: Cooldown) -> None:
        if not chain:
            raise ValueError("FallbackProvider needs at least one provider")
        self.chain = list(chain)
        self.cooldown = cooldown
        self.name: Provider = chain[0].name
        self.model = chain[0].model

    def _attempts(self) -> list[tuple[LLMProvider, Attempt]]:
        """Providers out of cooldown, in chain order; the primary alone when none is."""
        ready = [p for p in self.chain if self.cooldown.available(_key(p))] or self.chain[:1]
        return [
            (p, Attempt(p.name, p.model, number, fallback=p is not self.chain[0]))
            for number, p in enumerate(ready, start=1)
        ]

    def _served(
        self, result: LLMResult[T], provider: LLMProvider, attempt: Attempt, first: float
    ) -> LLMResult[T]:
        """Metrics are end to end: latency counts from the first attempt, failed ones included."""
        self.cooldown.record_success(_key(provider))
        return replace(
            result,
            latency_ms=_ms_since(first),
            attempts=attempt.number,
            fallback_used=attempt.fallback,
        )

    def _failed(self, exc: LLMError, provider: LLMProvider, attempt: Attempt) -> None:
        exc.attempt = attempt
        if falls_back(exc):
            self.cooldown.record_failure(_key(provider))

    def _log_fallback(
        self, exc: LLMError, attempt: Attempt, latency_ms: int, *, stream: bool
    ) -> None:
        # The attempt that serves (or fails last) is logged by the service as `llm_call`.
        fields = {
            "provider": attempt.provider,
            "model": attempt.model,
            "prompt_version": prompt_version_var.get(),
            "attempt": attempt.number,
            "fallback": attempt.fallback,
            "stream": stream,
            "outcome": exc.code,
            "cause": exc.cause,
            "upstream_status": exc.upstream_status,
            "latency_ms": latency_ms,  # this attempt's own duration
        }
        llm_logger.warning("llm_fallback", extra={"fields": fields})

    async def generate(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        attempts, first = self._attempts(), time.perf_counter()
        for provider, attempt in attempts:
            start = time.perf_counter()
            try:
                result = await provider.generate(
                    system=system, messages=messages, schema=schema, cache_key=cache_key
                )
            except LLMError as exc:
                self._failed(exc, provider, attempt)
                if not falls_back(exc) or attempt.number == len(attempts):
                    raise
                self._log_fallback(exc, attempt, _ms_since(start), stream=False)
            else:
                return self._served(result, provider, attempt, first)
        raise AssertionError("unreachable: the last attempt returns or raises")

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        attempts, first = self._attempts(), time.perf_counter()
        cause: str | None = "cooldown"  # a first attempt that is not the primary skipped it
        for provider, attempt in attempts:
            if attempt.fallback:
                yield ProviderSwitch(
                    provider=provider.name,
                    model=provider.model,
                    cause=cause,
                    attempt=attempt.number,
                )
            start, started = time.perf_counter(), False
            try:
                async with aclosing(
                    provider.stream(
                        system=system, messages=messages, schema=schema, cache_key=cache_key
                    )
                ) as events:
                    async for event in events:
                        started = started or isinstance(event, TextDelta)
                        yield (
                            self._served(event, provider, attempt, first)
                            if isinstance(event, LLMResult)
                            else event
                        )
                return
            except LLMError as exc:
                self._failed(exc, provider, attempt)
                if started or not falls_back(exc) or attempt.number == len(attempts):
                    raise
                self._log_fallback(exc, attempt, _ms_since(start), stream=True)
                cause = exc.cause or exc.code

    async def aclose(self) -> None:
        # Every close runs even if one raises; the error is re-raised afterwards.
        async with AsyncExitStack() as stack:
            for provider in self.chain:
                stack.push_async_callback(provider.aclose)
