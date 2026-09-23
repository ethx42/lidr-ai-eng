from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.schemas.estimation import Usage

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResult[M: BaseModel]:
    parsed: M
    usage: Usage
    latency_ms: int


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]: ...

    async def aclose(self) -> None: ...
