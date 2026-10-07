"""Throttled `partial` SSE events from the accumulated JSON text of a streamed estimate."""

import math
import time
from collections.abc import Callable

import jiter

from app.schemas.stream import PartialEvent


def _parse(snapshot: str) -> dict[str, object] | None:
    try:
        parsed = jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")
    except ValueError:  # empty, malformed, too deeply nested, or a lone surrogate
        return None
    return parsed if isinstance(parsed, dict) else None


class PartialSnapshotter:
    def __init__(
        self, *, min_interval: float = 0.1, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._last_emit = -math.inf
        self._last: dict[str, object] | None = None
        self._seq = 0

    def feed(self, snapshot: str) -> PartialEvent | None:
        now = self._clock()
        if now - self._last_emit < self._min_interval:
            return None
        return self._emit(snapshot, now)

    def flush(self, snapshot: str) -> PartialEvent | None:
        return self._emit(snapshot, self._clock())

    def _emit(self, snapshot: str, now: float) -> PartialEvent | None:
        breakdown = _parse(snapshot)
        if breakdown is None or breakdown == self._last:
            return None
        self._last, self._last_emit = breakdown, now
        self._seq += 1
        return PartialEvent(seq=self._seq, breakdown=breakdown)
