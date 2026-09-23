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


class LLMProvider(Protocol):
    name: Provider
    model: str

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]: ...

    async def aclose(self) -> None: ...
