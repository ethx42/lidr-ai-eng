"""Real SDK clients on a mock transport: retries and what goes on the wire."""

import copy
import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.observability import CLIENT_LOGGERS, configure_logging
from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimateRequest, EstimationBreakdown
from app.services.errors import InvalidModelOutput, LLMError, UpstreamError, UpstreamRateLimited
from app.services.llm_service import EstimationService
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.openai_provider import OpenAIProvider, openai_http_client
from app.services.providers.profiles import get_profile
from tests.factories import breakdown

PAYLOAD = breakdown().model_dump_json()

OPENAI_BODY = {
    "id": "resp_1",
    "object": "response",
    "created_at": 0,
    "status": "completed",
    "model": "gpt-4o-mini",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": PAYLOAD, "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 10,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 5,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 15,
    },
}

ANTHROPIC_BODY = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-4-5",
    "content": [{"type": "text", "text": PAYLOAD}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


def flaky(
    body: dict[str, Any], calls: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "1"}, json={"error": {}})
        return httpx.Response(200, json=body)

    return handler


COMMON = {"temperature": 0.2, "reasoning_effort": None, "max_output_tokens": 4096}


async def test_openai_retries_transient_failure() -> None:
    calls: list[httpx.Request] = []
    http = openai_http_client(transport=httpx.MockTransport(flaky(OPENAI_BODY, calls)))
    client = AsyncOpenAI(api_key="k", max_retries=2, http_client=http)
    provider = OpenAIProvider(
        client=client, model="gpt-4o-mini", profile=get_profile("gpt-4o-mini", "openai"), **COMMON
    )
    result = await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.parsed == breakdown()
    assert len(calls) == 2
    await provider.aclose()


async def test_anthropic_retries_transient_failure() -> None:
    calls: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(flaky(ANTHROPIC_BODY, calls)))
    client = AsyncAnthropic(api_key="k", max_retries=2, http_client=http)
    provider = AnthropicProvider(
        client=client,
        model="claude-haiku-4-5",
        profile=get_profile("claude-haiku-4-5", "anthropic"),
        **COMMON,
    )
    result = await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="k"
    )
    assert result.parsed == breakdown()
    assert len(calls) == 2
    await provider.aclose()


QUOTA_ERROR = {
    "error": {"message": "quota", "type": "insufficient_quota", "code": "credit_balance_exhausted"}
}
RATE_ERROR = {"error": {"message": "slow down", "type": "requests", "code": "rate_limit_exceeded"}}


def always_429(body: dict[str, Any], calls: list[int]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"retry-after-ms": "1"}, json=body)

    return handler


@pytest.mark.parametrize(
    "body,expected,attempts",
    [(QUOTA_ERROR, UpstreamError, 1), (RATE_ERROR, UpstreamRateLimited, 3)],
    ids=["quota-not-retried", "rate-limit-retried"],
)
async def test_openai_quota_is_not_retried(
    body: dict[str, Any], expected: type[Exception], attempts: int
) -> None:
    calls: list[httpx.Request] = []
    http = openai_http_client(transport=httpx.MockTransport(always_429(body, calls)))
    client = AsyncOpenAI(api_key="k", max_retries=2, http_client=http)
    provider = OpenAIProvider(
        client=client, model="gpt-4o-mini", profile=get_profile("gpt-4o-mini", "openai"), **COMMON
    )
    with pytest.raises(expected):
        await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    assert len(calls) == attempts
    await provider.aclose()


async def test_openai_sends_same_cache_key_on_the_wire() -> None:
    calls: list[httpx.Request] = []
    http = openai_http_client(transport=httpx.MockTransport(flaky(OPENAI_BODY, calls)))
    client = AsyncOpenAI(api_key="k", max_retries=2, http_client=http)
    provider = OpenAIProvider(
        client=client, model="gpt-4o-mini", profile=get_profile("gpt-4o-mini", "openai"), **COMMON
    )
    for _ in range(2):
        await provider.generate(
            system="s", user="u", schema=EstimationBreakdown, cache_key="estimator-v4"
        )
    keys = {json.loads(r.content)["prompt_cache_key"] for r in calls}
    assert keys == {"estimator-v4"}
    await provider.aclose()


async def test_anthropic_sends_no_routing_key_on_the_wire() -> None:
    calls: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(flaky(ANTHROPIC_BODY, calls)))
    client = AsyncAnthropic(api_key="k", max_retries=2, http_client=http)
    provider = AnthropicProvider(
        client=client,
        model="claude-haiku-4-5",
        profile=get_profile("claude-haiku-4-5", "anthropic"),
        **COMMON,
    )
    await provider.generate(
        system="s", user="u", schema=EstimationBreakdown, cache_key="estimator-v4"
    )
    assert all("estimator-v4" not in r.content.decode() for r in calls)
    await provider.aclose()


@pytest.fixture
def debug_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved = root.level, list(root.handlers)
    levels = {name: logging.getLogger(name).level for name in CLIENT_LOGGERS}
    configure_logging("DEBUG")
    yield
    root.setLevel(saved[0])
    root.handlers = saved[1]
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


Handler = Callable[[httpx.Request], httpx.Response]


def openai_provider(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAIProvider:
    http = openai_http_client(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(api_key="k", max_retries=0, http_client=http)
    return OpenAIProvider(
        client=client, model="gpt-4o-mini", profile=get_profile("gpt-4o-mini", "openai"), **COMMON
    )


def anthropic_provider(handler: Callable[[httpx.Request], httpx.Response]) -> AnthropicProvider:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnthropic(api_key="k", max_retries=0, http_client=http)
    return AnthropicProvider(
        client=client,
        model="claude-haiku-4-5",
        profile=get_profile("claude-haiku-4-5", "anthropic"),
        **COMMON,
    )


@pytest.mark.parametrize(
    "build,body",
    [(openai_provider, OPENAI_BODY), (anthropic_provider, ANTHROPIC_BODY)],
    ids=["openai", "anthropic"],
)
@pytest.mark.usefixtures("debug_logging")
async def test_debug_logging_leaks_no_transcript(
    build: Callable[[Handler], OpenAIProvider | AnthropicProvider],
    body: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "TRANSCRIPT-MARKER-7f3a"
    provider = build(lambda _: httpx.Response(200, json=body))
    await provider.generate(
        system="s", user=f"Client: {marker}", schema=EstimationBreakdown, cache_key="k"
    )
    await provider.aclose()
    assert caplog.records, "expected library records at INFO and above"
    assert all(marker not in record.getMessage() for record in caplog.records)


def test_llm_error_cause_prefers_reason_then_chained_class() -> None:
    try:
        try:
            raise ValueError("secret")
        except ValueError as inner:
            raise UpstreamError() from inner
    except LLMError as exc:
        assert (exc.cause, exc.upstream_status) == ("ValueError", None)
    assert InvalidModelOutput(reason="stop_reason:refusal").cause == "stop_reason:refusal"
    assert UpstreamError().cause is None


TRUNCATED = '{"project_name": "Yoga", "summ'
ANTHROPIC_TRUNCATED = copy.deepcopy(ANTHROPIC_BODY) | {"stop_reason": "max_tokens"}
ANTHROPIC_TRUNCATED["content"] = [{"type": "text", "text": TRUNCATED}]
OPENAI_TRUNCATED = copy.deepcopy(OPENAI_BODY) | {
    "status": "incomplete",
    "incomplete_details": {"reason": "max_output_tokens"},
}
OPENAI_TRUNCATED["output"][0]["content"][0]["text"] = TRUNCATED
ANTHROPIC_400 = {
    "type": "error",
    "error": {"type": "invalid_request_error", "message": "secret upstream detail"},
}


@pytest.mark.parametrize(
    "build,status,body,outcome,cause,upstream_status",
    [
        (anthropic_provider, 400, ANTHROPIC_400, "upstream_error", "BadRequestError", 400),
        (
            anthropic_provider,
            200,
            ANTHROPIC_TRUNCATED,
            "invalid_model_output",
            "stop_reason:max_tokens",
            None,
        ),
        (
            openai_provider,
            200,
            OPENAI_TRUNCATED,
            "invalid_model_output",
            "incomplete:max_output_tokens",
            None,
        ),
    ],
    ids=["anthropic-400", "anthropic-truncated", "openai-truncated"],
)
async def test_failed_call_logs_cause_without_upstream_detail(
    build: Callable[[Handler], OpenAIProvider | AnthropicProvider],
    status: int,
    body: dict[str, Any],
    outcome: str,
    cause: str,
    upstream_status: int | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = build(lambda _: httpx.Response(status, json=body))
    service = EstimationService(
        provider=provider, prompt=load_prompt(), weekly_capacity_hours=30, hourly_rate=None
    )
    with caplog.at_level(logging.INFO), pytest.raises(LLMError):
        await service.estimate(EstimateRequest(transcription="Client: we need a booking app."))
    await provider.aclose()
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    fields = record.fields  # type: ignore[attr-defined]
    assert (fields["outcome"], fields["cause"], fields["upstream_status"]) == (
        outcome,
        cause,
        upstream_status,
    )
    assert all("secret upstream detail" not in str(r.__dict__) for r in caplog.records)


async def test_anthropic_output_format_matches_sdk_parse() -> None:
    bodies: list[dict[str, Any]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=ANTHROPIC_BODY)

    provider = anthropic_provider(capture)
    await provider.generate(system="s", user="u", schema=EstimationBreakdown, cache_key="k")
    await provider.client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=10,
        messages=[{"role": "user", "content": "u"}],
        output_format=EstimationBreakdown,
    )
    await provider.aclose()
    ours, sdk = bodies
    assert ours["output_config"]["format"] == sdk["output_config"]["format"]
