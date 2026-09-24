import time
from typing import Any

import httpx2
import openai
import pydantic
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.config import Provider, ReasoningEffort
from app.schemas.estimation import Usage
from app.services.errors import (
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamUnavailable,
    from_status,
)
from app.services.providers.base import LLMResult, T
from app.services.providers.profiles import ModelProfile, request_params

QUOTA = "insufficient_quota"


async def _no_retry_on_quota(response: httpx2.Response) -> None:
    # OpenAI signals exhausted credits as 429, which the SDK would retry like a rate limit.
    if response.status_code == 429:
        await response.aread()
        if QUOTA in response.text:
            response.headers["x-should-retry"] = "false"


def openai_http_client(**kwargs: Any) -> DefaultAsyncHttpxClient:
    return DefaultAsyncHttpxClient(event_hooks={"response": [_no_retry_on_quota]}, **kwargs)


def map_error(exc: openai.APIError) -> LLMError:
    if QUOTA in (exc.code, exc.type):
        return UpstreamError()
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

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        start = time.perf_counter()
        try:
            # Raw first: `parse` fails on truncated JSON before the stop condition can be read.
            raw = await self.client.responses.with_raw_response.parse(
                model=self.model,
                instructions=system,
                input=user,
                text_format=schema,
                store=False,
                prompt_cache_key=cache_key,
                **self.params,
            )
        except openai.APIError as exc:
            raise map_error(exc) from exc

        envelope = raw.http_response.json()
        if envelope.get("status") == "incomplete":
            details = envelope.get("incomplete_details") or {}
            raise InvalidModelOutput(reason=f"incomplete:{details.get('reason')}")
        try:
            response = raw.parse()
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput() from exc

        parsed = response.output_parsed
        if parsed is None:
            refused = any(
                part.type == "refusal"
                for item in response.output
                if item.type == "message"
                for part in item.content
            )
            raise InvalidModelOutput(reason="refusal" if refused else "no_parsed_output")
        usage = response.usage
        details = usage.input_tokens_details if usage else None
        return LLMResult(
            parsed=parsed,
            usage=Usage(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cached_input_tokens=(details.cached_tokens or 0) if details else 0,
                cache_write_tokens=(details.cache_write_tokens or 0) if details else 0,
            ),
            latency_ms=round((time.perf_counter() - start) * 1000),
        )

    async def aclose(self) -> None:
        await self.client.close()
