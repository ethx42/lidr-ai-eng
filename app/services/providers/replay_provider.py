"""Deterministic streams without API calls: replays the recorded cassette that matches the prompt
pair, or synthesises a stream from a fixture breakdown when none does."""

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pydantic
from pydantic import BaseModel

from app.config import Provider
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.errors import InvalidModelOutput
from app.services.providers.base import LLMResult, StreamEvent, T, TextDelta

type Chunks = list[tuple[float, str]]  # (ms since the first chunk, text)


def cassette_key(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()


class Cassette(BaseModel):
    """`<cassette_dir>/<key>.json`: one recorded provider stream."""

    key: str
    provider: Provider
    model: str
    recorded_at: str
    usage: Usage
    chunks: Chunks


class ReplayProvider:
    name: Provider = "replay"

    def __init__(
        self,
        *,
        cassette_dir: Path,
        fallback: Sequence[EstimationBreakdown],
        delay_scale: float,
        chunk_chars: int = 24,
        chunk_delay: float = 0.02,
        model: str = "replay",
    ) -> None:
        if not fallback:
            raise ValueError("ReplayProvider needs at least one fallback breakdown")
        self.cassette_dir = cassette_dir
        self.fallback = fallback
        # Multiplies every delay: 0 = instant, 1 = as recorded, 2 = twice as slow.
        self.delay_scale = delay_scale
        self.chunk_chars = chunk_chars
        self.chunk_delay = chunk_delay
        self.model = model

    def _recording(self, key: str) -> tuple[Chunks, Usage]:
        path = self.cassette_dir / f"{key}.json"
        if path.is_file():
            cassette = Cassette.model_validate_json(path.read_bytes())
            return cassette.chunks, cassette.usage
        text = self.fallback[int(key, 16) % len(self.fallback)].model_dump_json()
        pieces = [text[i : i + self.chunk_chars] for i in range(0, len(text), self.chunk_chars)]
        return [(n * self.chunk_delay * 1000, piece) for n, piece in enumerate(pieces)], Usage()

    def _result(self, schema: type[T], text: str, usage: Usage, start: float) -> LLMResult[T]:
        try:
            parsed = schema.model_validate_json(text)
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput() from exc
        return LLMResult(
            parsed=parsed,
            usage=usage,
            latency_ms=round((time.perf_counter() - start) * 1000),
            provider=self.name,
            model=self.model,
        )

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        start = time.perf_counter()
        chunks, usage = self._recording(cassette_key(system, user))
        return self._result(schema, "".join(text for _, text in chunks), usage, start)

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncIterator[StreamEvent[T]]:
        start = time.perf_counter()
        chunks, usage = self._recording(cassette_key(system, user))
        previous, snapshot = 0.0, ""
        for elapsed, text in chunks:
            await asyncio.sleep((elapsed - previous) / 1000 * self.delay_scale)
            previous, snapshot = elapsed, snapshot + text
            yield TextDelta(text=text, snapshot=snapshot)
        yield self._result(schema, snapshot, usage, start)

    async def aclose(self) -> None:
        pass
