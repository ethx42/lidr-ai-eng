import time
from typing import Any

import openai
import pydantic
from openai import AsyncOpenAI

from app.config import Provider, ReasoningEffort
from app.schemas.estimation import Usage
from app.services.errors import InvalidModelOutput, LLMError, UpstreamUnavailable, from_status
from app.services.providers.base import LLMResult, T
from app.services.providers.profiles import ModelProfile, request_params


def map_error(exc: openai.APIError) -> LLMError:
    if isinstance(exc, openai.APIConnectionError):
        return UpstreamUnavailable()
    if isinstance(exc, openai.APIStatusError):
        return from_status(exc.status_code)
    return InvalidModelOutput()


class OpenAIProvider:
    name: Provider = "openai"

    def __init__(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        profile: ModelProfile,
        temperature: float,
        reasoning_effort: ReasoningEffort | None,
        max_output_tokens: int,
    ) -> None:
        self.client = client
        self.model = model
        self.params: dict[str, Any] = request_params(
            profile,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
        )

    async def generate(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        start = time.perf_counter()
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=system,
                input=user,
                text_format=schema,
                store=False,
                **self.params,
            )
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput() from exc
        except openai.APIError as exc:
            raise map_error(exc) from exc

        parsed = response.output_parsed
        if response.status == "incomplete" or parsed is None:
            raise InvalidModelOutput()
        usage = response.usage
        return LLMResult(
            parsed=parsed,
            usage=Usage(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cached_input_tokens=(usage.input_tokens_details.cached_tokens or 0) if usage else 0,
            ),
            latency_ms=round((time.perf_counter() - start) * 1000),
        )

    async def aclose(self) -> None:
        await self.client.close()
