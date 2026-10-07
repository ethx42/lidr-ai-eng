from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.config import Provider
from app.schemas.estimation import Usage

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResult[M: BaseModel]:
    parsed: M
    usage: Usage
    latency_ms: int
    provider: Provider
    model: str
    attempts: int = 1
    fallback_used: bool = False


@dataclass(frozen=True)
class TextDelta:
    text: str
    snapshot: str  # all text received so far


@dataclass(frozen=True)
class ProviderSwitch:
    """Sent before a call to any provider but the primary (`attempt` counts calls, from 1)."""

    provider: Provider
    model: str
    cause: str | None  # why the previous candidate was left: its error, or "cooldown"
    attempt: int


# A stream yields deltas (and switches before the first delta), then exactly one LLMResult.
type StreamEvent[M: BaseModel] = TextDelta | ProviderSwitch | LLMResult[M]


class LLMProvider(Protocol):
    name: Provider
    model: str

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]: ...

    def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]: ...

    async def aclose(self) -> None: ...
