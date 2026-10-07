import time
from collections.abc import AsyncGenerator
from functools import cache
from typing import Any

import httpx2
import openai
import pydantic
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from openai.lib._parsing._responses import type_to_text_format_param
from openai.types.responses import Response, ResponseUsage
from pydantic import BaseModel

from app.config import Provider, ReasoningEffort
from app.schemas.estimation import Usage
from app.services.errors import (
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
    from_status,
)
from app.services.providers.base import LLMResult, StreamEvent, T, TextDelta
from app.services.providers.profiles import ModelProfile, request_params

QUOTA = "insufficient_quota"


@cache
def text_format(schema: type[BaseModel]) -> dict[str, Any]:  # JSON request fragment
    """The `text.format` that `responses.parse(text_format=schema)` would send."""
    return {**type_to_text_format_param(schema)}


async def _no_retry_on_quota(response: httpx2.Response) -> None:
    # OpenAI signals exhausted credits as 429, which the SDK would retry like a rate limit.
    if response.status_code == 429:
        await response.aread()
        if QUOTA in response.text:
            response.headers["x-should-retry"] = "false"


def openai_http_client(**kwargs: Any) -> DefaultAsyncHttpxClient:
    return DefaultAsyncHttpxClient(event_hooks={"response": [_no_retry_on_quota]}, **kwargs)


def stream_error(code: str | None) -> LLMError:
    """An error reported inside a 200 stream: an `error` event, `response.failed` or a payload."""
    if code == QUOTA:
        return UpstreamError(reason=QUOTA)
    reason = f"stream_error:{code}" if code else "stream_error"
    if code == "server_error":
        return UpstreamUnavailable(reason=reason)
    if code == "rate_limit_exceeded":
        return UpstreamRateLimited(reason=reason)
    return UpstreamError(reason=reason)


def map_error(exc: openai.APIError) -> LLMError:
    if QUOTA in (exc.code, exc.type):
        return UpstreamError(reason=QUOTA)
    if isinstance(exc, openai.APIConnectionError):
        return UpstreamUnavailable()
    if isinstance(exc, openai.APIStatusError):
        return from_status(exc.status_code)
    # A stream payload shaped `{"error": {...}}` raises a bare APIError (often with only a type).
    code = exc.code or exc.type
    return stream_error(code) if code else InvalidModelOutput()


def _refused(response: Response) -> bool:
    return any(
        part.type == "refusal"
        for item in response.output
        if item.type == "message"
        for part in item.content
    )


def _usage(usage: ResponseUsage | None) -> Usage:
    details = usage.input_tokens_details if usage else None
    return Usage(
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        cached_input_tokens=(details.cached_tokens or 0) if details else 0,
        cache_write_tokens=(details.cache_write_tokens or 0) if details else 0,
    )


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
            raise InvalidModelOutput(reason="refusal" if _refused(response) else "no_parsed_output")
        return self._result(parsed, response.usage, start)

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        # The schema goes raw (no `text_format=`): the parsing helper raises ValidationError on
        # truncated JSON before the terminal event says why. Validated once the stream has ended.
        start = time.perf_counter()
        terminal: Response | None = None
        try:
            async with self.client.responses.stream(
                model=self.model,
                instructions=system,
                input=user,
                store=False,
                prompt_cache_key=cache_key,
                stream_options={"include_obfuscation": False},  # server-to-server TLS
                **{**self.params, "text": self._text_param(schema)},
            ) as events:
                async for event in events:
                    match event.type:
                        case "response.output_text.delta":
                            yield TextDelta(text=event.delta, snapshot=event.snapshot)
                        case "response.completed" | "response.incomplete" | "response.failed":
                            terminal = event.response
                        case "error":
                            raise stream_error(event.code)
        except openai.APIError as exc:
            raise map_error(exc) from exc
        except RuntimeError as exc:
            # The SDK helper's state machine rejects out-of-order events (an event before
            # `response.created`, a content event before its output item).
            raise UpstreamUnavailable(reason="stream_protocol") from exc
        yield self._parse_terminal(terminal, schema, start)

    def _text_param(self, schema: type[BaseModel]) -> dict[str, Any]:  # JSON request fragment
        return {**self.params.get("text", {}), "format": text_format(schema)}

    def _parse_terminal(
        self, terminal: Response | None, schema: type[T], start: float
    ) -> LLMResult[T]:
        if terminal is None:
            raise UpstreamUnavailable(reason="no_terminal_event")
        if terminal.status == "incomplete":
            details = terminal.incomplete_details
            raise InvalidModelOutput(reason=f"incomplete:{details.reason if details else None}")
        if terminal.status == "failed":
            raise stream_error(terminal.error.code if terminal.error else None)
        if _refused(terminal):
            raise InvalidModelOutput(reason="refusal")
        try:
            parsed = schema.model_validate_json(terminal.output_text)
        except pydantic.ValidationError as exc:
            raise InvalidModelOutput() from exc
        return self._result(parsed, terminal.usage, start)

    def _result(self, parsed: T, usage: ResponseUsage | None, start: float) -> LLMResult[T]:
        return LLMResult(
            parsed=parsed,
            usage=_usage(usage),
            latency_ms=round((time.perf_counter() - start) * 1000),
            provider=self.name,
            model=self.model,
        )

    async def aclose(self) -> None:
        await self.client.close()
