from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx2 as httpx
import openai
import pytest
from pydantic import ValidationError

from app.schemas.estimation import EstimationBreakdown
from app.services.errors import (
    InvalidModelOutput,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.openai_provider import OpenAIProvider
from app.services.providers.profiles import get_profile
from tests.factories import breakdown

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


def response(parsed: Any = None, status: str = "completed", cached: int | None = 512) -> Any:
    usage = SimpleNamespace(
        input_tokens=2000,
        output_tokens=900,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
    )
    return SimpleNamespace(output_parsed=parsed, status=status, usage=usage)


def make(model: str = "gpt-4o-mini", **parse_kwargs: Any) -> tuple[OpenAIProvider, AsyncMock]:
    parse = AsyncMock(**parse_kwargs)
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse), close=AsyncMock())
    provider = OpenAIProvider(
        client=client,  # type: ignore[arg-type]
        model=model,
        profile=get_profile(model, "openai"),
        temperature=0.2,
        reasoning_effort=None,
        max_output_tokens=4096,
    )
    return provider, parse


async def test_success_maps_parsed_and_usage() -> None:
    provider, parse = make(return_value=response(breakdown()))
    result = await provider.generate(system="SYS", user="USER", schema=EstimationBreakdown)
    assert result.parsed == breakdown()
    assert result.usage.input_tokens == 2000
    assert result.usage.output_tokens == 900
    assert result.usage.cached_input_tokens == 512
    kwargs = parse.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["instructions"] == "SYS"
    assert kwargs["input"] == "USER"
    assert kwargs["text_format"] is EstimationBreakdown
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_output_tokens"] == 4096
    assert "reasoning" not in kwargs


async def test_missing_cached_tokens_is_zero() -> None:
    provider, _ = make(return_value=response(breakdown(), cached=None))
    result = await provider.generate(system="s", user="u", schema=EstimationBreakdown)
    assert result.usage.cached_input_tokens == 0


@pytest.mark.parametrize(
    "resp",
    [response(None), response(breakdown(), status="incomplete")],
    ids=["refusal-or-no-parse", "incomplete"],
)
async def test_invalid_output(resp: Any) -> None:
    provider, _ = make(return_value=resp)
    with pytest.raises(InvalidModelOutput):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown)


async def test_schema_validation_error_is_invalid_output() -> None:
    try:
        EstimationBreakdown.model_validate({})
    except ValidationError as exc:
        error = exc
    provider, _ = make(side_effect=error)
    with pytest.raises(InvalidModelOutput):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown)


def status_error(
    cls: type[openai.APIStatusError], code: int, body: object = None
) -> openai.APIStatusError:
    return cls("boom", response=httpx.Response(code, request=REQUEST), body=body)


QUOTA_BODY = {"type": "insufficient_quota", "code": "credit_balance_exhausted"}


@pytest.mark.parametrize(
    "exc,expected",
    [
        (status_error(openai.RateLimitError, 429), UpstreamRateLimited),
        (status_error(openai.RateLimitError, 429, QUOTA_BODY), UpstreamError),
        (
            status_error(openai.RateLimitError, 429, {"code": "insufficient_quota"}),
            UpstreamError,
        ),
        (openai.APITimeoutError(request=REQUEST), UpstreamUnavailable),
        (openai.APIConnectionError(request=REQUEST), UpstreamUnavailable),
        (status_error(openai.InternalServerError, 500), UpstreamUnavailable),
        (status_error(openai.AuthenticationError, 401), UpstreamError),
        (status_error(openai.BadRequestError, 400), UpstreamError),
    ],
)
async def test_sdk_error_mapping(exc: Exception, expected: type[Exception]) -> None:
    provider, _ = make(side_effect=exc)
    with pytest.raises(expected):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown)


async def test_reasoning_model_params() -> None:
    parse = AsyncMock(return_value=response(breakdown()))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse), close=AsyncMock())
    provider = OpenAIProvider(
        client=client,  # type: ignore[arg-type]
        model="gpt-5-mini",
        profile=get_profile("gpt-5-mini", "openai"),
        temperature=0.2,
        reasoning_effort="low",
        max_output_tokens=4096,
    )
    await provider.generate(system="s", user="u", schema=EstimationBreakdown)
    kwargs = parse.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "low"}
    assert "temperature" not in kwargs


async def test_aclose_closes_client() -> None:
    provider, _ = make()
    await provider.aclose()
    provider.client.close.assert_awaited_once()  # type: ignore[attr-defined]
