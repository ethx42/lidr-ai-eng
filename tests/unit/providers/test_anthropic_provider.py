from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx2 as httpx
import pytest
from pydantic import ValidationError

from app.schemas.estimation import EstimationBreakdown
from app.services.errors import (
    InvalidModelOutput,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.profiles import get_profile
from tests.factories import breakdown

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def message(
    parsed: Any = None,
    stop_reason: str = "end_turn",
    cache_read: int | None = 4000,
    cache_write: int | None = 0,
) -> Any:
    usage = SimpleNamespace(
        input_tokens=300,
        output_tokens=900,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, usage=usage)


def make(
    model: str = "claude-haiku-4-5", effort: Any = None, **parse_kwargs: Any
) -> tuple[AnthropicProvider, AsyncMock]:
    parse = AsyncMock(**parse_kwargs)
    client = SimpleNamespace(messages=SimpleNamespace(parse=parse), close=AsyncMock())
    provider = AnthropicProvider(
        client=client,  # type: ignore[arg-type]
        model=model,
        profile=get_profile(model, "anthropic"),
        temperature=0.2,
        reasoning_effort=effort,
        max_output_tokens=4096,
    )
    return provider, parse


async def test_success_with_cached_system_block() -> None:
    provider, parse = make(return_value=message(breakdown()))
    result = await provider.generate(
        system="SYS", user="USER", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.parsed == breakdown()
    assert result.usage.input_tokens == 4300
    assert result.usage.cached_input_tokens == 4000
    assert result.usage.output_tokens == 900
    kwargs = parse.call_args.kwargs
    assert kwargs["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert kwargs["output_format"] is EstimationBreakdown
    assert kwargs["extra_body"] == {"temperature": 0.2}
    assert "temperature" not in kwargs
    assert kwargs["max_tokens"] == 4096


async def test_missing_cache_usage_is_zero() -> None:
    provider, _ = make(return_value=message(breakdown(), cache_read=None, cache_write=None))
    result = await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.usage.cached_input_tokens == 0
    assert result.usage.cache_write_tokens == 0


async def test_cache_write_reported_and_no_routing_key_sent() -> None:
    provider, parse = make(return_value=message(breakdown(), cache_read=0, cache_write=4000))
    result = await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.usage.cache_write_tokens == 4000
    assert result.usage.input_tokens == 4300
    assert "prompt_cache_key" not in parse.call_args.kwargs


@pytest.mark.parametrize(
    "msg",
    [
        message(breakdown(), stop_reason="refusal"),
        message(breakdown(), stop_reason="max_tokens"),
        message(breakdown(), stop_reason="model_context_window_exceeded"),
        message(None),
    ],
    ids=["refusal", "max_tokens", "context_window", "no-parse"],
)
async def test_invalid_output(msg: Any) -> None:
    provider, _ = make(return_value=msg)
    with pytest.raises(InvalidModelOutput):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")


async def test_schema_validation_error_is_invalid_output() -> None:
    try:
        EstimationBreakdown.model_validate({})
    except ValidationError as exc:
        error = exc
    provider, _ = make(side_effect=error)
    with pytest.raises(InvalidModelOutput):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")


def status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    return cls("boom", response=httpx.Response(code, request=REQUEST), body=None)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (status_error(anthropic.RateLimitError, 429), UpstreamRateLimited),
        (anthropic.APITimeoutError(request=REQUEST), UpstreamUnavailable),
        (anthropic.APIConnectionError(request=REQUEST), UpstreamUnavailable),
        (status_error(anthropic.InternalServerError, 500), UpstreamUnavailable),
        (status_error(anthropic.APIStatusError, 529), UpstreamUnavailable),
        (status_error(anthropic.AuthenticationError, 401), UpstreamError),
        (status_error(anthropic.BadRequestError, 400), UpstreamError),
    ],
)
async def test_sdk_error_mapping(exc: Exception, expected: type[Exception]) -> None:
    provider, _ = make(side_effect=exc)
    with pytest.raises(expected):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")


async def test_opus_adaptive_thinking_without_temperature() -> None:
    provider, parse = make(model="claude-opus-5", effort="high", return_value=message(breakdown()))
    await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    kwargs = parse.call_args.kwargs
    assert "temperature" not in kwargs
    assert "extra_body" not in kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
