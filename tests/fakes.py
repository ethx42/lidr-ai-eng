from typing import Any, TypeVar

from pydantic import BaseModel

from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.providers.base import LLMResult
from tests.factories import breakdown

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    """Offline LLMProvider: returns a canned breakdown or raises a configured error."""

    def __init__(
        self,
        result: EstimationBreakdown | None = None,
        error: Exception | None = None,
        name: str = "openai",
        model: str = "fake-model",
    ) -> None:
        self.name = name
        self.model = model
        self.result = result or breakdown()
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def generate(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        return LLMResult(
            parsed=schema.model_validate(self.result.model_dump()),
            usage=Usage(input_tokens=1200, output_tokens=800, cached_input_tokens=1024),
            latency_ms=42,
        )

    async def aclose(self) -> None:
        self.closed = True
