"""Real SDK clients on a mock transport: a transient failure is retried, then succeeds."""

from collections.abc import Callable
from typing import Any

import httpx2 as httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.schemas.estimation import EstimationBreakdown
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.openai_provider import OpenAIProvider
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
        "input_tokens_details": {"cached_tokens": 0},
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


def flaky(body: dict[str, Any], calls: list[int]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "1"}, json={"error": {}})
        return httpx.Response(200, json=body)

    return handler


COMMON = {"temperature": 0.2, "reasoning_effort": None, "max_output_tokens": 4096}


async def test_openai_retries_transient_failure() -> None:
    calls: list[int] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(flaky(OPENAI_BODY, calls)))
    client = AsyncOpenAI(api_key="k", max_retries=2, http_client=http)
    provider = OpenAIProvider(
        client=client, model="gpt-4o-mini", profile=get_profile("gpt-4o-mini", "openai"), **COMMON
    )
    result = await provider.generate(system="s", user="u", schema=EstimationBreakdown)
    assert result.parsed == breakdown()
    assert len(calls) == 2
    await provider.aclose()


async def test_anthropic_retries_transient_failure() -> None:
    calls: list[int] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(flaky(ANTHROPIC_BODY, calls)))
    client = AsyncAnthropic(api_key="k", max_retries=2, http_client=http)
    provider = AnthropicProvider(
        client=client,
        model="claude-haiku-4-5",
        profile=get_profile("claude-haiku-4-5", "anthropic"),
        **COMMON,
    )
    result = await provider.generate(system="s", user="u", schema=EstimationBreakdown)
    assert result.parsed == breakdown()
    assert len(calls) == 2
    await provider.aclose()
