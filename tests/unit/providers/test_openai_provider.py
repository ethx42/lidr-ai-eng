from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

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


def response(
    parsed: Any = None,
    status: str = "completed",
    cached: int | None = 512,
    written: int = 1024,
    refusal: bool = False,
) -> Any:
    usage = SimpleNamespace(
        input_tokens=2000,
        output_tokens=900,
        input_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=written),
    )
    content = [SimpleNamespace(type="refusal")] if refusal else []
    output = [SimpleNamespace(type="message", content=content)]
    return SimpleNamespace(output_parsed=parsed, status=status, usage=usage, output=output)


def raw(resp: Any, incomplete: str | None = None, parse_error: Exception | None = None) -> Any:
    """Stands in for the lazily parsed `with_raw_response` result."""
    envelope = {
        "status": resp.status,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
    }
    return SimpleNamespace(
        http_response=SimpleNamespace(json=lambda: envelope),
        parse=Mock(return_value=resp, side_effect=parse_error),
    )


def client_for(parse: AsyncMock) -> Any:
    return SimpleNamespace(
        responses=SimpleNamespace(with_raw_response=SimpleNamespace(parse=parse)),
        close=AsyncMock(),
    )


def make(model: str = "gpt-4o-mini", **parse_kwargs: Any) -> tuple[OpenAIProvider, AsyncMock]:
    if "return_value" in parse_kwargs and not hasattr(parse_kwargs["return_value"], "parse"):
        parse_kwargs["return_value"] = raw(parse_kwargs["return_value"])
    parse = AsyncMock(**parse_kwargs)
    client = client_for(parse)
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
    result = await provider.generate(
        system="SYS", user="USER", schema=EstimationBreakdown, cache_key="estimator-v9"
    )
    assert result.parsed == breakdown()
    assert result.usage.input_tokens == 2000
    assert result.usage.output_tokens == 900
    assert result.usage.cached_input_tokens == 512
    assert result.usage.cache_write_tokens == 1024
    kwargs = parse.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["instructions"] == "SYS"
    assert kwargs["input"] == "USER"
    assert kwargs["text_format"] is EstimationBreakdown
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_output_tokens"] == 4096
    assert kwargs["prompt_cache_key"] == "estimator-v9"
    assert "reasoning" not in kwargs


async def test_missing_cached_tokens_is_zero() -> None:
    provider, _ = make(return_value=response(breakdown(), cached=None))
    result = await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.usage.cached_input_tokens == 0


@pytest.mark.parametrize(
    "resp,reason",
    [
        (raw(response(None)), "no_parsed_output"),
        (raw(response(None, refusal=True)), "refusal"),
        (
            raw(response(None, status="incomplete"), "max_output_tokens"),
            "incomplete:max_output_tokens",
        ),
    ],
    ids=["no-parse", "refusal", "incomplete"],
)
async def test_invalid_output(resp: Any, reason: str) -> None:
    provider, _ = make(return_value=resp)
    with pytest.raises(InvalidModelOutput) as info:
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    assert info.value.cause == reason


async def test_schema_validation_error_is_invalid_output() -> None:
    try:
        EstimationBreakdown.model_validate({})
    except ValidationError as exc:
        error = exc
    provider, _ = make(return_value=raw(response(), parse_error=error))
    with pytest.raises(InvalidModelOutput) as info:
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    assert info.value.cause == "ValidationError"


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
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")


async def test_reasoning_model_params() -> None:
    parse = AsyncMock(return_value=raw(response(breakdown())))
    provider = OpenAIProvider(
        client=client_for(parse),
        model="gpt-5-mini",
        profile=get_profile("gpt-5-mini", "openai"),
        temperature=0.2,
        reasoning_effort="low",
        max_output_tokens=4096,
    )
    await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    kwargs = parse.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "low"}
    assert "temperature" not in kwargs


async def test_aclose_closes_client() -> None:
    provider, _ = make()
    await provider.aclose()
    provider.client.close.assert_awaited_once()  # type: ignore[attr-defined]
