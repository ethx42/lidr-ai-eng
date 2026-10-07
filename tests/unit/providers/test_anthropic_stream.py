"""Anthropic streaming on a real SDK client, served recorded SSE bodies (fixtures/sse/anthropic)."""

import json
from collections.abc import AsyncIterator, Callable
from itertools import accumulate
from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropic

from app.config import ReasoningEffort
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.errors import (
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.anthropic_provider import AnthropicProvider, output_format
from app.services.providers.base import ChatMessage, LLMResult, StreamEvent, TextDelta
from app.services.providers.profiles import get_profile
from scripts.record_sse_fixture import MAX_OUTPUT_TOKENS, anthropic_body, parse_sse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sse" / "anthropic"
SSE_HEADERS = {"content-type": "text/event-stream"}

Handler = Callable[[httpx.Request], httpx.Response]
type JSON = dict[str, Any]  # parsed request/error bodies; tests index into them freely
MESSAGES = [ChatMessage("user", "u")]
HISTORY = [ChatMessage("user", "u1"), ChatMessage("assistant", "a1"), ChatMessage("user", "u2")]


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


def serve(body: str) -> Handler:
    return lambda _: httpx.Response(200, headers=SSE_HEADERS, content=body.encode())


def provider_for(
    handler: Handler,
    model: str = "claude-haiku-4-5",
    effort: ReasoningEffort | None = None,
    max_output_tokens: int = 4096,
) -> AnthropicProvider:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AnthropicProvider(
        client=AsyncAnthropic(api_key="k", max_retries=0, http_client=http),
        model=model,
        profile=get_profile(model, "anthropic"),
        temperature=0.2,
        reasoning_effort=effort,
        max_output_tokens=max_output_tokens,
    )


async def collect(
    provider: AnthropicProvider, received: list[StreamEvent[EstimationBreakdown]] | None = None
) -> list[StreamEvent[EstimationBreakdown]]:
    events = [] if received is None else received
    async for event in provider.stream(
        system="s", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
    ):
        events.append(event)
    return events


async def test_completed_streams_deltas_then_the_parsed_result() -> None:
    body = fixture("completed")
    events = parse_sse(body)
    final_text = "".join(e["delta"]["text"] for e in events if e["type"] == "content_block_delta")
    usage = next(e for e in events if e["type"] == "message_delta")["usage"]
    # The recording had no cache hit or write; give both usage events some (message_delta's
    # cumulative counts overwrite message_start's) so the input total is visible.
    assert body.count('"cache_read_input_tokens":0') == 2
    assert body.count('"cache_creation_input_tokens":0') == 2
    body = body.replace('"cache_read_input_tokens":0', '"cache_read_input_tokens":4000')
    body = body.replace('"cache_creation_input_tokens":0', '"cache_creation_input_tokens":512')

    *deltas, result = await collect(provider_for(serve(body)))

    assert deltas and all(isinstance(d, TextDelta) for d in deltas)
    texts = [d.text for d in deltas if isinstance(d, TextDelta)]
    snapshots = [d.snapshot for d in deltas if isinstance(d, TextDelta)]
    assert snapshots == list(accumulate(texts))
    assert snapshots[-1] == final_text
    assert isinstance(result, LLMResult)
    assert result.parsed == EstimationBreakdown.model_validate_json(final_text)
    assert (result.provider, result.model) == ("anthropic", "claude-haiku-4-5")
    assert result.usage.model_dump() == {
        "input_tokens": usage["input_tokens"] + 4000 + 512,
        "output_tokens": usage["output_tokens"],
        "cached_input_tokens": 4000,
        "cache_write_tokens": 512,
    }
    assert result.latency_ms >= 0


@pytest.mark.parametrize(
    "name,reason",
    [
        ("max_tokens", "max_tokens"),
        ("context_window_exceeded", "model_context_window_exceeded"),
        ("refusal", "refusal"),
    ],
)
async def test_invalid_stop_reasons_are_invalid_output(name: str, reason: str) -> None:
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(InvalidModelOutput) as info:
        await collect(provider_for(serve(fixture(name))), received)
    assert info.value.cause == f"stop_reason:{reason}"
    assert received and all(isinstance(e, TextDelta) for e in received)


@pytest.mark.parametrize("name", ["max_tokens", "context_window_exceeded", "refusal"])
async def test_invalid_stop_reasons_carry_the_billed_usage(name: str) -> None:
    body = fixture(name)
    usage = next(e for e in parse_sse(body) if e["type"] == "message_delta")["usage"]
    assert usage["output_tokens"] > 0
    with pytest.raises(InvalidModelOutput) as info:
        await collect(provider_for(serve(body)))
    assert info.value.usage == Usage(
        input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"]
    )


@pytest.mark.parametrize(
    "name,kind,expected",
    [
        ("overloaded_midstream", "overloaded_error", UpstreamUnavailable),
        ("overloaded_midstream", "api_error", UpstreamUnavailable),
        ("overloaded_midstream", "timeout_error", UpstreamUnavailable),
        ("rate_limit_midstream", "rate_limit_error", UpstreamRateLimited),
    ],
)
async def test_error_events_inside_the_stream_are_mapped_by_type(
    name: str, kind: str, expected: type[LLMError]
) -> None:
    recorded = "overloaded_error" if name == "overloaded_midstream" else "rate_limit_error"
    body = fixture(name).replace(f'"type":"{recorded}"', f'"type":"{kind}"')
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(LLMError) as info:
        await collect(provider_for(serve(body)), received)
    assert type(info.value) is expected
    assert info.value.cause == kind
    # The SDK raises the in-stream error as a status error carrying the stream's 200.
    upstream = info.value.__cause__
    assert isinstance(upstream, anthropic.APIStatusError)
    assert upstream.status_code == 200
    assert received and all(isinstance(e, TextDelta) for e in received)


@pytest.mark.parametrize("name", ["overloaded_midstream", "rate_limit_midstream"])
async def test_error_events_inside_the_stream_report_no_upstream_status(name: str) -> None:
    # The 200 is the stream's: logged next to an unavailable outcome, it would mislead.
    with pytest.raises(LLMError) as info:
        await collect(provider_for(serve(fixture(name))))
    assert info.value.upstream_status is None


async def test_other_error_events_inside_the_stream_are_upstream_errors() -> None:
    body = fixture("overloaded_midstream").replace(
        '"type":"overloaded_error"', '"type":"invalid_request_error"'
    )
    with pytest.raises(LLMError) as info:
        await collect(provider_for(serve(body)))
    assert type(info.value) is UpstreamError
    assert info.value.cause == "APIStatusError"


def http_error(status: int, body: JSON | str) -> Handler:
    content = body if isinstance(body, str) else json.dumps(body)
    return lambda _: httpx.Response(status, content=content.encode())


def error_body(kind: str, message: str | None = None, **extra: JSON) -> JSON:
    return {"type": "error", "error": {"type": kind, "message": message or kind, **extra}}


# Documented at platform.claude.com/docs/en/api/rate-limits (spend cap, own spend limits) and
# /api/errors (402); the credit-balance message is observed, not documented.
SPEND_CAP = error_body(
    "rate_limit_error",
    "You have reached your API usage limits: your organization has crossed its monthly API usage"
    " threshold, set based on your organization's API tier.",
    details={"error_code": "enforced_spend_limit_reached"},
)
OWN_LIMIT = "You have reached your specified API usage limits. You will regain access on ..."
WORKSPACE_LIMIT = "You have reached your specified workspace API usage limits. You will regain ..."
CREDIT = "Your credit balance is too low to access the Anthropic API."


@pytest.mark.parametrize(
    "status,body,expected,cause",
    [
        (529, error_body("overloaded_error"), UpstreamUnavailable, "overloaded_error"),
        (500, error_body("api_error"), UpstreamUnavailable, "api_error"),
        (504, error_body("timeout_error"), UpstreamUnavailable, "timeout_error"),
        (429, error_body("rate_limit_error"), UpstreamRateLimited, "rate_limit_error"),
        (400, error_body("invalid_request_error"), UpstreamError, "BadRequestError"),
        (502, {"error": "Bad gateway"}, UpstreamUnavailable, "InternalServerError"),
        (503, "<html>Service Unavailable</html>", UpstreamUnavailable, "InternalServerError"),
        (402, error_body("billing_error"), UpstreamError, "insufficient_quota"),
        (429, SPEND_CAP, UpstreamError, "insufficient_quota"),
        (400, error_body("invalid_request_error", OWN_LIMIT), UpstreamError, "insufficient_quota"),
        (
            400,
            error_body("invalid_request_error", WORKSPACE_LIMIT),
            UpstreamError,
            "insufficient_quota",
        ),
        (400, error_body("invalid_request_error", CREDIT), UpstreamError, "insufficient_quota"),
    ],
    ids=[
        "529",
        "500",
        "504",
        "429",
        "400",
        "502-flat-error",
        "503-html",
        "402-billing",
        "429-spend-cap",
        "400-own-limit",
        "400-workspace-limit",
        "400-credit-balance",
    ],
)
async def test_http_errors_map_the_same_on_both_paths(
    status: int, body: JSON | str, expected: type[LLMError], cause: str
) -> None:
    provider = provider_for(http_error(status, body))
    with pytest.raises(LLMError) as streamed:
        await collect(provider)
    with pytest.raises(LLMError) as blocking:
        await provider.generate(
            system="s", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
        )
    for info in (streamed, blocking):
        assert type(info.value) is expected
        assert info.value.cause == cause
        assert info.value.upstream_status == status


def without(body: str, *types: str) -> str:
    return "".join(
        f"{b}\n\n" for b in body.split("\n\n") if b and b.split("\n")[0][7:] not in types
    )


@pytest.mark.parametrize(
    "body",
    [
        without(fixture("completed"), "message_start"),
        without(fixture("completed"), "content_block_start"),
    ],
    ids=["event-before-message-start", "delta-before-block"],
)
async def test_out_of_order_events_are_unavailable(body: str) -> None:
    with pytest.raises(UpstreamUnavailable) as info:
        await collect(provider_for(serve(body)))
    assert info.value.cause == "stream_protocol"


@pytest.mark.parametrize(
    "body",
    [
        fixture("completed").rsplit("event: message_stop", 1)[0],
        fixture("completed").rsplit("event: content_block_stop", 1)[0],
        "",
    ],
    ids=["cut-before-message-stop", "cut-mid-text", "empty"],
)
async def test_stream_without_message_stop_is_unavailable(body: str) -> None:
    with pytest.raises(UpstreamUnavailable) as info:
        await collect(provider_for(serve(body)))
    assert info.value.cause == "no_terminal_event"


def capturing(bodies: list[JSON]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(400, json=error_body("invalid_request_error"))

    return handler


@pytest.mark.parametrize(
    "model,effort,config",
    [
        ("claude-haiku-4-5", None, {}),
        ("claude-opus-5", "high", {"effort": "high"}),
    ],
    ids=["haiku", "opus-effort"],
)
async def test_wire_output_config_and_cached_system_block(
    model: str, effort: ReasoningEffort | None, config: JSON
) -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies), model=model, effort=effort)
    with pytest.raises(UpstreamError):
        await collect(provider)
    with pytest.raises(anthropic.BadRequestError):
        await provider.client.messages.parse(
            model=model,
            max_tokens=16,
            messages=[{"role": "user", "content": "u"}],
            output_format=EstimationBreakdown,
            **({"output_config": config} if config else {}),
        )
    ours, sdk = bodies
    assert ours["output_config"] == {**config, "format": output_format(EstimationBreakdown)}
    assert ours["output_config"] == sdk["output_config"]
    assert ours["system"] == [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}]
    assert ours["messages"] == [{"role": "user", "content": "u"}]
    assert ours["stream"] is True


@pytest.mark.parametrize("stream", [False, True], ids=["generate", "stream"])
async def test_anthropic_sends_history_as_messages(stream: bool) -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies))
    args = {"system": "SYS", "messages": HISTORY, "schema": EstimationBreakdown, "cache_key": "k"}
    with pytest.raises(UpstreamError):
        if stream:
            [_ async for _ in provider.stream(**args)]
        else:
            await provider.generate(**args)
    [body] = bodies
    assert body["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
    ]


async def test_fixture_recorder_sends_the_provider_body() -> None:
    bodies: list[JSON] = []
    provider = provider_for(capturing(bodies), max_output_tokens=MAX_OUTPUT_TOKENS)
    with pytest.raises(UpstreamError):
        await collect(provider)
    assert bodies == [anthropic_body("s", "u", temperature=0.2)]


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, body: str) -> None:
        self.chunks = [f"{block}\n\n".encode() for block in body.split("\n\n") if block]
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class BrokenBody(TrackedBody):
    """Delivers the first `after` events, then fails like a stalled or dropped connection."""

    def __init__(self, body: str, after: int, error: Exception) -> None:
        super().__init__(body)
        self.chunks, self.error = self.chunks[:after], error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        raise self.error


def broken(after: int, error: Exception) -> Handler:
    body = BrokenBody(fixture("completed"), after, error)
    return lambda _: httpx.Response(200, headers=SSE_HEADERS, stream=body)


# Every httpx2.RequestError raised while reading the body, as OpenAI's SDK wraps them.
TRANSPORT_ERRORS = [
    httpx.ReadTimeout("stalled"),
    httpx.RemoteProtocolError("peer closed connection"),
    httpx.ReadError("connection reset"),
    httpx.DecodingError("corrupt content encoding"),
]


@pytest.mark.parametrize("error", TRANSPORT_ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("after,deltas", [(3, 0), (6, 3)], ids=["before-text", "after-text"])
async def test_transport_failure_mid_body_is_unavailable(
    after: int, deltas: int, error: Exception
) -> None:
    received: list[StreamEvent[EstimationBreakdown]] = []
    with pytest.raises(UpstreamUnavailable) as info:
        await collect(provider_for(broken(after, error)), received)
    assert info.value.cause == "stream_transport"
    assert info.value.__cause__ is error
    assert len(received) == deltas and all(isinstance(e, TextDelta) for e in received)


async def test_httpx_stream_misuse_is_not_reported_as_a_protocol_error() -> None:
    # httpx2.StreamError subclasses RuntimeError; it is a bug here, never a fallback trigger.
    with pytest.raises(httpx.StreamClosed):
        await collect(provider_for(broken(6, httpx.StreamClosed())))


async def test_closing_the_generator_closes_the_upstream_stream() -> None:
    body = TrackedBody(fixture("completed"))
    provider = provider_for(lambda _: httpx.Response(200, headers=SSE_HEADERS, stream=body))
    events = provider.stream(
        system="s", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
    )

    assert isinstance(await anext(events), TextDelta)
    assert not body.closed
    await events.aclose()
    assert body.closed
