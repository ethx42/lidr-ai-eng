import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Callable, Sequence
from itertools import pairwise
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Provider
from app.schemas.estimation import EstimateResponse, EstimationBreakdown, Usage
from app.services.cache import CacheStatus
from app.services.errors import UpstreamUnavailable
from app.services.providers.base import ChatMessage, LLMResult, StreamEvent, TextDelta
from tests.factories import breakdown

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    """Offline LLMProvider: returns a canned breakdown or raises a configured error, either before
    anything is streamed (`error`) or after `stream_error_after_chunks` deltas (`stream_error`).
    Each call answers the next `queue`d breakdown, else `respond_with(messages)`, else `result`."""

    def __init__(
        self,
        result: EstimationBreakdown | None = None,
        error: Exception | None = None,
        name: Provider = "openai",
        model: str = "fake-model",
        stream_error_after_chunks: int | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.result = result or breakdown()
        self.error = error
        self.stream_error_after_chunks = stream_error_after_chunks
        self.stream_error = stream_error
        self.respond_with: Callable[[Sequence[ChatMessage]], EstimationBreakdown] | None = None
        self.queued: deque[EstimationBreakdown] = deque()
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.closed_streams = 0

    def queue(self, result: EstimationBreakdown) -> None:
        self.queued.append(result)

    def _answer(self, messages: Sequence[ChatMessage]) -> EstimationBreakdown:
        if self.queued:
            return self.queued.popleft()
        return self.respond_with(messages) if self.respond_with else self.result

    def _record(
        self,
        system: str,
        messages: Sequence[ChatMessage],
        schema: type[BaseModel],
        cache_key: str,
    ) -> None:
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "schema": schema,
                "cache_key": cache_key,
            }
        )

    def _result(self, schema: type[T]) -> LLMResult[T]:
        """The answer to the call just recorded."""
        return LLMResult(
            parsed=schema.model_validate(self._answer(self.calls[-1]["messages"]).model_dump()),
            usage=Usage(
                input_tokens=1200,
                output_tokens=800,
                cached_input_tokens=1024,
                cache_write_tokens=176,
            ),
            latency_ms=42,
            provider=self.name,
            model=self.model,
        )

    async def generate(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        self._record(system, messages, schema, cache_key)
        if self.error:
            raise self.error
        return self._result(schema)

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        self._record(system, messages, schema, cache_key)
        if self.error:
            raise self.error
        result = self._result(schema)
        text = result.parsed.model_dump_json()
        cuts = [len(text) * i // 3 for i in range(4)]
        finished = False
        try:
            for sent, (start, end) in enumerate(pairwise(cuts)):
                if self.stream_error and sent == self.stream_error_after_chunks:
                    raise self.stream_error
                yield TextDelta(text=text[start:end], snapshot=text[:end])
            yield result
            finished = True
        finally:
            if not finished:
                self.closed_streams += 1

    async def aclose(self) -> None:
        self.closed = True


class GatedFakeProvider(FakeProvider):
    """`generate` answers only once `release` is set: a turn held in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def generate(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        await self.release.wait()
        return await super().generate(
            system=system, messages=messages, schema=schema, cache_key=cache_key
        )


class SpyCache:
    """A ResponseCache that counts lookups and writes, and always misses."""

    def __init__(self) -> None:
        self.gets = 0
        self.sets = 0

    async def get(self, key: str) -> tuple[EstimateResponse | None, CacheStatus]:
        self.gets += 1
        return None, "miss"

    async def set(self, key: str, value: EstimateResponse) -> None:
        self.sets += 1

    async def aclose(self) -> None:
        return None


class SlowFakeProvider(FakeProvider):
    """Streams one delta, then stalls forever: an upstream that stops mid-answer."""

    first_delta = '{"project_name": "Yo'

    def __init__(self) -> None:
        super().__init__()
        self.stream_closed = asyncio.Event()

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        self._record(system, messages, schema, cache_key)
        try:
            yield TextDelta(text=self.first_delta, snapshot=self.first_delta)
            await asyncio.Event().wait()
        finally:
            self.closed_streams += 1
            self.stream_closed.set()


class TickingFakeProvider(SlowFakeProvider):
    """Streams a changed snapshot every `interval` seconds and never finishes: a long answer."""

    def __init__(self, interval: float = 0.11) -> None:
        super().__init__()
        self.interval = interval

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        self._record(system, messages, schema, cache_key)
        snapshot = self.first_delta
        try:
            while True:
                yield TextDelta(text=snapshot[-1], snapshot=snapshot)
                await asyncio.sleep(self.interval)
                snapshot += "o"
        finally:
            self.closed_streams += 1
            self.stream_closed.set()


class SlowToFailProvider(FakeProvider):
    """Raises UpstreamUnavailable after `delay` seconds, before any output: a timed-out primary."""

    def __init__(self, delay: float = 0.06, **kwargs: Any) -> None:
        super().__init__(error=UpstreamUnavailable(), **kwargs)
        self.delay = delay

    async def generate(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        await asyncio.sleep(self.delay)
        return await super().generate(
            system=system, messages=messages, schema=schema, cache_key=cache_key
        )

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        await asyncio.sleep(self.delay)
        async for event in super().stream(
            system=system, messages=messages, schema=schema, cache_key=cache_key
        ):
            yield event


class SlowToFinishProvider(FakeProvider):
    """Streams its deltas at once, then takes `delay` seconds before the final result."""

    def __init__(self, delay: float = 0.03, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        async for event in super().stream(
            system=system, messages=messages, schema=schema, cache_key=cache_key
        ):
            if isinstance(event, LLMResult):
                await asyncio.sleep(self.delay)
            yield event
