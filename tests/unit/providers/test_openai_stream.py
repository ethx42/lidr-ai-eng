"""OpenAI streaming on a real SDK client, served recorded SSE bodies (tests/fixtures/sse/openai)."""

import json
from collections.abc import AsyncIterator, Callable
from itertools import accumulate
from pathlib import Path
from typing import Any

import httpx2 as httpx
import openai
import pytest
from openai import AsyncOpenAI

from app.schemas.estimation import EstimationBreakdown
from app.services.errors import (
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.base import LLMResult, StreamEvent, TextDelta
from app.services.providers.openai_provider import OpenAIProvider, openai_http_client
from app.services.providers.profiles import get_profile
from scripts.record_sse_fixture import CACHE_KEY, MAX_OUTPUT_TOKENS, openai_body, parse_sse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sse" / "openai"
SSE_HEADERS = {"content-type": "text/event-stream"}

Handler = Callable[[httpx.Request], httpx.Response]
type JSON = dict[str, Any]  # parsed request/error bodies; tests index into them freely


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


def serve(body: str) -> Handler:
    return lambda _: httpx.Response(200, headers=SSE_HEADERS, content=body.encode())


def provider_for(handler: Handler, max_output_tokens: int = 4096) -> OpenAIProvider:
    http = openai_http_client(transport=httpx.MockTransport(handler))
    return OpenAIProvider(
        client=AsyncOpenAI(api_key="k", max_retries=0, http_client=http),
        model="gpt-4o-mini",
        profile=get_profile("gpt-4o-mini", "openai"),
        temperature=0.2,
        reasoning_effort=None,
        max_output_tokens=max_output_tokens,
    )


async def collect(
    provider: OpenAIProvider, received: list[StreamEvent[EstimationBreakdown]] | None = None
) -> list[StreamEvent[EstimationBreakdown]]:
    events = [] if received is None else received
    async for event in provider.stream(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    ):
        events.append(event)
    return events


async def test_completed_streams_deltas_then_the_parsed_result() -> None:
    body = fixture("completed")
    *_, completed = parse_sse(body)
    final_text = completed["response"]["output"][0]["content"][0]["text"]
    usage = completed["response"]["usage"]
    # The recording had no cache hit; give the terminal usage one so the mapping is visible.
    assert body.count('"cached_tokens":0') == 1
    body = body.replace('"cached_tokens":0', '"cached_tokens":512')

    *deltas, result = await collect(provider_for(serve(body)))

    assert deltas and all(isinstance(d, TextDelta) for d in deltas)
    texts = [d.text for d in deltas if isinstance(d, TextDelta)]
    snapshots = [d.snapshot for d in deltas if isinstance(d, TextDelta)]
    assert snapshots == list(accumulate(texts))
    assert snapshots[-1] == final_text
    assert isinstance(result, LLMResult)
    assert result.parsed == EstimationBreakdown.model_validate_json(final_text)
    assert (result.provider, result.model) == ("openai", "gpt-4o-mini")
    assert result.usage.model_dump() == {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cached_input_tokens": 512,
        "cache_write_tokens": 0,
    }
    assert result.latency_ms >= 0


async def test_incomplete_is_invalid_output_with_its_reason() -> None:
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(InvalidModelOutput) as info:
        await collect(provider_for(serve(fixture("incomplete_max_tokens"))), received)
    assert info.value.cause == "incomplete:max_output_tokens"
    assert received and all(isinstance(e, TextDelta) for e in received)


async def test_refusal_is_invalid_output_and_streams_no_text() -> None:
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(InvalidModelOutput) as info:
        await collect(provider_for(serve(fixture("refusal"))), received)
    assert info.value.cause == "refusal"
    assert received == []


@pytest.mark.parametrize(
    "name,code,expected,cause",
    [
        ("failed", "server_error", UpstreamUnavailable, "stream_error:server_error"),
        ("failed", "invalid_prompt", UpstreamError, "stream_error:invalid_prompt"),
        ("failed", None, UpstreamError, "stream_error"),
        (
            "error_event",
            "rate_limit_exceeded",
            UpstreamRateLimited,
            "stream_error:rate_limit_exceeded",
        ),
        ("error_event", "server_error", UpstreamUnavailable, "stream_error:server_error"),
        ("error_event", "invalid_prompt", UpstreamError, "stream_error:invalid_prompt"),
        ("error_event", "insufficient_quota", UpstreamError, "insufficient_quota"),
        ("error_event", None, UpstreamError, "stream_error"),
    ],
)
async def test_errors_inside_the_stream_are_mapped(
    name: str, code: str | None, expected: type[LLMError], cause: str
) -> None:
    recorded = '"code":"server_error"' if name == "failed" else '"code":"rate_limit_exceeded"'
    body = fixture(name).replace(recorded, f'"code":{json.dumps(code)}')
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(LLMError) as info:
        await collect(provider_for(serve(body)), received)
    assert type(info.value) is expected
    assert info.value.cause == cause
    assert received and all(isinstance(e, TextDelta) for e in received)


@pytest.mark.parametrize(
    "error,expected,cause",
    [
        (
            {"type": "requests", "code": "rate_limit_exceeded"},
            UpstreamRateLimited,
            "stream_error:rate_limit_exceeded",
        ),
        ({"type": "server_error", "code": None}, UpstreamUnavailable, "stream_error:server_error"),
        ({"type": "insufficient_quota", "code": None}, UpstreamError, "insufficient_quota"),
    ],
    ids=["code", "type-only", "quota"],
)
async def test_nested_error_payload_is_mapped_by_code_or_type(
    error: JSON, expected: type[LLMError], cause: str
) -> None:
    body = fixture("error_event").rsplit("event: error", 1)[0]
    body += f"event: error\ndata: {json.dumps({'type': 'error', 'error': error})}\n\n"
    with pytest.raises(LLMError) as info:
        await collect(provider_for(serve(body)))
    assert type(info.value) is expected
    assert info.value.cause == cause


def without(body: str, *types: str) -> str:
    return "".join(
        f"{b}\n\n" for b in body.split("\n\n") if b and b.split("\n")[0][7:] not in types
    )


@pytest.mark.parametrize(
    "body",
    [
        fixture("error_event").rsplit("\n\n", 2)[-2] + "\n\n",
        without(fixture("completed"), "response.output_item.added", "response.content_part.added"),
    ],
    ids=["event-before-created", "delta-before-item"],
)
async def test_out_of_order_events_are_unavailable(body: str) -> None:
    with pytest.raises(UpstreamUnavailable) as info:
        await collect(provider_for(serve(body)))
    assert info.value.cause == "stream_protocol"
    assert isinstance(info.value.__cause__, RuntimeError)


async def test_stream_without_a_terminal_event_is_unavailable() -> None:
    body = fixture("completed").rsplit("event: response.completed", 1)[0]
    with pytest.raises(UpstreamUnavailable) as info:
        await collect(provider_for(serve(body)))
    assert info.value.cause == "no_terminal_event"


QUOTA_ERROR = {"error": {"message": "quota", "type": "insufficient_quota", "code": None}}
RATE_ERROR = {"error": {"message": "slow down", "type": "requests", "code": "rate_limit_exceeded"}}


@pytest.mark.parametrize(
    "body,expected,cause",
    [
        (RATE_ERROR, UpstreamRateLimited, "RateLimitError"),
        (QUOTA_ERROR, UpstreamError, "insufficient_quota"),
    ],
    ids=["rate-limited", "quota"],
)
async def test_http_429_before_any_event(body: JSON, expected: type[LLMError], cause: str) -> None:
    provider = provider_for(lambda _: httpx.Response(429, json=body))
    with pytest.raises(LLMError) as info:
        await collect(provider)
    assert type(info.value) is expected
    assert info.value.cause == cause


def capturing(bodies: list[JSON]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "captured", "type": "x"}})

    return handler


async def test_wire_text_format_matches_sdk_parse() -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies))
    with pytest.raises(UpstreamError):
        await collect(provider)
    with pytest.raises(openai.BadRequestError):
        await provider.client.responses.parse(
            model="gpt-4o-mini", input="u", text_format=EstimationBreakdown
        )
    ours, sdk = bodies
    assert ours["text"]["format"] == sdk["text"]["format"]
    assert ours["stream"] is True
    assert ours["stream_options"] == {"include_obfuscation": False}
    assert (ours["store"], ours["prompt_cache_key"]) == (False, "k")


async def test_text_options_in_params_are_merged_with_the_format() -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies))
    provider.params["text"] = {"verbosity": "low"}
    with pytest.raises(UpstreamError):
        await collect(provider)
    [body] = bodies
    assert body["text"]["verbosity"] == "low"
    assert body["text"]["format"]["name"] == "EstimationBreakdown"


async def test_fixture_recorder_sends_the_provider_body() -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies), max_output_tokens=MAX_OUTPUT_TOKENS)
    with pytest.raises(UpstreamError):
        async for _ in provider.stream(
            system="s", user="u", schema=EstimationBreakdown, cache_key=CACHE_KEY
        ):
            pass
    assert bodies == [openai_body("s", "u", temperature=0.2)]


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, body: str) -> None:
        self.chunks = [f"{block}\n\n".encode() for block in body.split("\n\n") if block]
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def test_closing_the_generator_closes_the_upstream_stream() -> None:
    body = TrackedBody(fixture("completed"))
    provider = provider_for(lambda _: httpx.Response(200, headers=SSE_HEADERS, stream=body))
    events = provider.stream(system="s", user="u", schema=EstimationBreakdown, cache_key="k")

    assert isinstance(await anext(events), TextDelta)
    assert not body.closed
    await events.aclose()
    assert body.closed
