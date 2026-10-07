import time
from collections.abc import AsyncGenerator, Sequence
from functools import cache
from typing import Any

import anthropic
import httpx2
import pydantic
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient, transform_schema
from anthropic.types import Message
from pydantic import BaseModel, TypeAdapter

from app.config import Provider, ReasoningEffort
from app.schemas.estimation import Usage
from app.services.errors import (
    QUOTA,
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
    from_status,
)
from app.services.providers.base import ChatMessage, LLMResult, StreamEvent, T, TextDelta
from app.services.providers.profiles import ModelProfile, request_params

INVALID_STOP_REASONS = {"refusal", "max_tokens", "model_context_window_exceeded"}

# By `error.type`, which is all a mid-stream `event: error` carries (its status is the stream's
# 200); `timeout_error` is the 504 type, unavailable like the status it stands for.
STREAM_ERROR_TYPES: dict[str, type[LLMError]] = {
    "overloaded_error": UpstreamUnavailable,
    "api_error": UpstreamUnavailable,
    "timeout_error": UpstreamUnavailable,
    "rate_limit_error": UpstreamRateLimited,
}
# Exhausted spend (platform.claude.com/docs/en/api/rate-limits): the tier cap is a 429 marked by
# this code, a spend limit you set is a 400 with the message prefix; the credit-balance 400 is
# observed, not documented. Unlike rate limits, retrying any of them fails until access resumes.
SPEND_CAP = "enforced_spend_limit_reached"
QUOTA_MESSAGES = ("You have reached your specified", "Your credit balance is too low")


@cache
def output_format(schema: type[BaseModel]) -> dict[str, Any]:  # JSON request fragment
    """The `output_config.format` that `messages.parse(output_format=schema)` would send."""
    return {"type": "json_schema", "schema": transform_schema(TypeAdapter(schema).json_schema())}


async def _no_retry_on_spend_cap(response: httpx2.Response) -> None:
    # The SDK would retry the spend-cap 429 like a rate limit.
    if response.status_code == 429:
        await response.aread()
        if SPEND_CAP in response.text:
            response.headers["x-should-retry"] = "false"


def anthropic_http_client(**kwargs: Any) -> DefaultAsyncHttpxClient:
    return DefaultAsyncHttpxClient(event_hooks={"response": [_no_retry_on_spend_cap]}, **kwargs)


def _quota_exhausted(error: dict[str, Any]) -> bool:  # the API's `error` object, arbitrary JSON
    details = error.get("details")
    message = error.get("message")
    return (
        error.get("type") == "billing_error"
        or (isinstance(details, dict) and details.get("error_code") == SPEND_CAP)
        or (
            error.get("type") == "invalid_request_error"
            and isinstance(message, str)
            and message.startswith(QUOTA_MESSAGES)
        )
    )


def map_error(exc: anthropic.APIError) -> LLMError:
    if isinstance(exc, anthropic.APIConnectionError):
        return UpstreamUnavailable()
    if isinstance(exc, anthropic.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error")
        error = error if isinstance(error, dict) else {}
        if _quota_exhausted(error):
            return UpstreamError(reason=QUOTA)
        kind = error.get("type")
        if kind in STREAM_ERROR_TYPES:
            return STREAM_ERROR_TYPES[kind](reason=kind)
        return from_status(exc.status_code)
    return InvalidModelOutput()


def _usage(usage: anthropic.types.Usage) -> Usage:
    cache_read = usage.cache_read_input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    # Anthropic reports uncached input separately; report the total like OpenAI does.
    return Usage(
        input_tokens=usage.input_tokens + cache_read + cache_write,
        output_tokens=usage.output_tokens,
        cached_input_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


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
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        # Anthropic caches by content (the cache_control block); it takes no routing key.
        # `create` + validation instead of `parse`, which fails on truncated JSON before the
        # stop reason can be read.
        start = time.perf_counter()
        try:
            message = await self.client.messages.create(**self._request(system, messages, schema))
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        return self._finish(message, schema, start)

    async def stream(
        self, *, system: str, messages: Sequence[ChatMessage], schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        # The schema goes raw (no `output_format=`): the parsing helper raises ValidationError on
        # truncated JSON at `content_block_stop`, before `message_delta` says why.
        start = time.perf_counter()
        message: Message | None = None
        try:
            async with self.client.messages.stream(
                **self._request(system, messages, schema)
            ) as events:
                async for event in events:
                    match event.type:
                        case "text":
                            yield TextDelta(text=event.text, snapshot=event.snapshot)
                        case "message_stop":
                            message = event.message
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        except httpx2.RequestError as exc:
            # Unlike OpenAI's, this SDK does not wrap errors raised while reading the body
            # (transport and decoding errors alike).
            raise UpstreamUnavailable(reason="stream_transport") from exc
        except httpx2.StreamError:
            raise  # a RuntimeError, but our misuse of the response, not the upstream's
        except (RuntimeError, IndexError) as exc:
            # The SDK accumulator rejects an event before `message_start` (RuntimeError) and
            # indexes content blocks by position (IndexError for a delta without its block).
            raise UpstreamUnavailable(reason="stream_protocol") from exc
        # `get_final_message()` would return whatever was accumulated, even from a cut stream.
        if message is None:
            raise UpstreamUnavailable(reason="no_terminal_event")
        yield self._finish(message, schema, start)

    def _request(
        self, system: str, messages: Sequence[ChatMessage], schema: type[BaseModel]
    ) -> dict[str, Any]:  # keyword arguments for messages.create/stream
        return {
            **self.params,
            "model": self.model,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "output_config": {
                **self.params.get("output_config", {}),
                "format": output_format(schema),
            },
        }

    def _finish(self, message: Message, schema: type[T], start: float) -> LLMResult[T]:
        # Read first: an invalid answer is billed too, and its error reports the usage.
        usage = _usage(message.usage)
        if message.stop_reason in INVALID_STOP_REASONS:
            raise InvalidModelOutput(reason=f"stop_reason:{message.stop_reason}", usage=usage)
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise InvalidModelOutput(reason="no_parsed_output", usage=usage)
        try:
            parsed = schema.model_validate_json(text)
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput(usage=usage) from exc
        return LLMResult(
            parsed=parsed,
            usage=usage,
            latency_ms=round((time.perf_counter() - start) * 1000),
            provider=self.name,
            model=self.model,
        )

    async def aclose(self) -> None:
        await self.client.close()
