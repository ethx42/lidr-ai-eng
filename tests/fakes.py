import asyncio
from collections.abc import AsyncGenerator
from itertools import pairwise
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Provider
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.providers.base import LLMResult, StreamEvent, TextDelta
from tests.factories import breakdown

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    """Offline LLMProvider: returns a canned breakdown or raises a configured error."""

    def __init__(
        self,
        result: EstimationBreakdown | None = None,
        error: Exception | None = None,
        name: Provider = "openai",
        model: str = "fake-model",
    ) -> None:
        self.name = name
        self.model = model
        self.result = result or breakdown()
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.closed_streams = 0

    def _record(self, system: str, user: str, schema: type[BaseModel], cache_key: str) -> None:
        self.calls.append(
            {"system": system, "user": user, "schema": schema, "cache_key": cache_key}
        )

    def _result(self, schema: type[T]) -> LLMResult[T]:
        return LLMResult(
            parsed=schema.model_validate(self.result.model_dump()),
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
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        self._record(system, user, schema, cache_key)
        if self.error:
            raise self.error
        return self._result(schema)

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        self._record(system, user, schema, cache_key)
        if self.error:
            raise self.error
        result = self._result(schema)
        text = result.parsed.model_dump_json()
        cuts = [len(text) * i // 3 for i in range(4)]
        finished = False
        try:
            for start, end in pairwise(cuts):
                yield TextDelta(text=text[start:end], snapshot=text[:end])
            yield result
            finished = True
        finally:
            if not finished:
                self.closed_streams += 1

    async def aclose(self) -> None:
        self.closed = True


class SlowFakeProvider(FakeProvider):
    """Streams one delta, then stalls forever: an upstream that stops mid-answer."""

    first_delta = '{"project_name": "Yo'

    def __init__(self) -> None:
        super().__init__()
        self.stream_closed = asyncio.Event()

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        self._record(system, user, schema, cache_key)
        try:
            yield TextDelta(text=self.first_delta, snapshot=self.first_delta)
            await asyncio.Event().wait()
        finally:
            self.closed_streams += 1
            self.stream_closed.set()
