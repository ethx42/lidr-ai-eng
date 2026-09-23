import time
from functools import cache
from typing import Any

import anthropic
import pydantic
from anthropic import AsyncAnthropic, transform_schema
from pydantic import BaseModel, TypeAdapter

from app.config import Provider, ReasoningEffort
from app.schemas.estimation import Usage
from app.services.errors import InvalidModelOutput, LLMError, UpstreamUnavailable, from_status
from app.services.providers.base import LLMResult, T
from app.services.providers.profiles import ModelProfile, request_params

INVALID_STOP_REASONS = {"refusal", "max_tokens", "model_context_window_exceeded"}


@cache
def output_format(schema: type[BaseModel]) -> dict[str, Any]:
    """The `output_config.format` that `messages.parse(output_format=schema)` would send."""
    return {"type": "json_schema", "schema": transform_schema(TypeAdapter(schema).json_schema())}


def map_error(exc: anthropic.APIError) -> LLMError:
    if isinstance(exc, anthropic.APIConnectionError):
        return UpstreamUnavailable()
    if isinstance(exc, anthropic.APIStatusError):
        return from_status(exc.status_code)
    return InvalidModelOutput()


class AnthropicProvider:
    name: Provider = "anthropic"

    def __init__(
        self,
        *,
        client: AsyncAnthropic,
        model: str,
        profile: ModelProfile,
        temperature: float,
        reasoning_effort: ReasoningEffort | None,
        max_output_tokens: int,
    ) -> None:
        self.client = client
        self.model = model
        params = request_params(
            profile,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
        )
        # SDK 1.x dropped sampling args from its signature; older models still honour them.
        sampling = {k: params.pop(k) for k in ("temperature",) if k in params}
        self.params: dict[str, Any] = params | ({"extra_body": sampling} if sampling else {})

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        # Anthropic caches by content (the cache_control block); it takes no routing key.
        # `create` + validation instead of `parse`, which fails on truncated JSON before the
        # stop reason can be read.
        start = time.perf_counter()
        output_config = {**self.params.get("output_config", {}), "format": output_format(schema)}
        try:
            message = await self.client.messages.create(
                model=self.model,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                **{**self.params, "output_config": output_config},
            )
        except anthropic.APIError as exc:
            raise map_error(exc) from exc

        if message.stop_reason in INVALID_STOP_REASONS:
            raise InvalidModelOutput(reason=f"stop_reason:{message.stop_reason}")
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise InvalidModelOutput(reason="no_parsed_output")
        try:
            parsed = schema.model_validate_json(text)
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput() from exc
        usage = message.usage
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        # Anthropic reports uncached input separately; report the total like OpenAI does.
        input_tokens = usage.input_tokens + cache_read + cache_write
        return LLMResult(
            parsed=parsed,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
            latency_ms=round((time.perf_counter() - start) * 1000),
        )

    async def aclose(self) -> None:
        await self.client.close()
