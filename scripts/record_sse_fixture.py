"""Record a raw provider SSE body as a unit-test fixture (live, budget-guarded).

`make record-cassettes SSE=<openai|anthropic>` streams one tiny request with the JSON body the
provider sends, saves the events to tests/fixtures/sse/<provider>/completed.txt (ids replaced,
order kept) and derives the failure fixtures from that recording.
"""

import asyncio
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx2

from app.config import Settings
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.pricing import cost_usd
from app.services.providers.anthropic_provider import output_format, system_blocks
from app.services.providers.openai_provider import text_format
from app.services.providers.profiles import get_profile, request_params
from scripts.live_budget import ensure_budget, record_spend

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sse"
OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_VERSION = "2023-06-01"
MAX_OUTPUT_TOKENS = 800
CACHE_KEY = "record-sse-fixture"
ESTIMATE_USD = {"openai": 0.002, "anthropic": 0.01}
SYSTEM = (
    "You estimate software projects from meeting transcripts. Keep the answer minimal: one "
    "requirement, no assumptions, one open question, two tasks, one team member, one risk."
)
TRANSCRIPT = "Client: We need a page where guests book a table at our restaurant."
REFUSAL = "I'm sorry, but I can't help with that request."
IDS = re.compile(r'"(resp|msg)_[A-Za-z0-9]+"')

type Event = dict[str, Any]  # one SSE `data:` payload, arbitrary JSON


def openai_body(system: str, user: str, *, temperature: float) -> dict[str, Any]:  # JSON body
    """The JSON body `OpenAIProvider.stream` sends (pinned by a unit test)."""
    params = request_params(
        get_profile(OPENAI_MODEL, "openai"),
        temperature=temperature,
        reasoning_effort=None,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return {
        "model": OPENAI_MODEL,
        "instructions": system,
        "input": [{"role": "user", "content": user}],
        "store": False,
        "prompt_cache_key": CACHE_KEY,
        "text": {"format": text_format(EstimationBreakdown)},
        "stream_options": {"include_obfuscation": False},
        "stream": True,
        **params,
    }


def anthropic_body(system: str, user: str, *, temperature: float) -> dict[str, Any]:  # JSON body
    """The JSON body `AnthropicProvider.stream` sends (pinned by a unit test)."""
    params = request_params(
        get_profile(ANTHROPIC_MODEL, "anthropic"),
        temperature=temperature,
        reasoning_effort=None,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return {
        "model": ANTHROPIC_MODEL,
        "system": system_blocks(system),
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": output_format(EstimationBreakdown)},
        "stream": True,
        **params,
    }


def parse_sse(text: str) -> list[Event]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def to_sse(events: list[Event]) -> str:
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for e in events
    )


def numbered(events: list[Event]) -> list[Event]:
    """OpenAI events carry their position in the stream."""
    return [{**event, "sequence_number": n} for n, event in enumerate(events)]


def replaced(value: Any, old: object, new: object) -> Any:  # any JSON value
    if value == old:
        return new
    if isinstance(value, dict):
        return {k: replaced(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [replaced(v, old, new) for v in value]
    return value


def derive_openai(directory: Path = FIXTURES / "openai") -> None:
    """Failure fixtures edited from the recorded `completed.txt`."""
    events = parse_sse((directory / "completed.txt").read_text())
    first_delta = next(i for i, e in enumerate(events) if e["type"] == "response.output_text.delta")
    head, deltas = events[:first_delta], [e for e in events if e["type"].endswith("text.delta")]
    done = [e for e in events if e["type"].endswith(".done")]
    completed = events[-1]
    text = "".join(d["delta"] for d in deltas)
    some = deltas[: len(deltas) // 2]

    cut = "".join(d["delta"] for d in some)
    incomplete = replaced([*done, completed], text, cut)
    incomplete[-1] = {
        "type": "response.incomplete",
        "response": incomplete[-1]["response"]
        | {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
    }
    for item in (incomplete[-2]["item"], incomplete[-1]["response"]["output"][0]):
        item["status"] = "incomplete"

    part = {"type": "refusal", "refusal": REFUSAL}
    where = {k: deltas[0][k] for k in ("item_id", "output_index", "content_index")}
    refusal = [
        *(
            e
            if e["type"] != "response.content_part.added"
            else e | {"part": part | {"refusal": ""}}
            for e in head
        ),
        *(
            {"type": "response.refusal.delta", **where, "delta": word}
            for word in re.findall(r"\S+\s*", REFUSAL)
        ),
        {"type": "response.refusal.done", **where, "refusal": REFUSAL},
        *(copy.deepcopy(e) for e in done if e["type"] != "response.output_text.done"),
        copy.deepcopy(completed),
    ]
    refusal[-3]["part"] = part
    refusal[-2]["item"]["content"] = [part]
    refusal[-1]["response"]["output"][0]["content"] = [part]

    error = {"code": "server_error", "message": "The server had an error processing your request."}
    failed_response = completed["response"] | {
        "status": "failed",
        "error": error,
        "output": [],
        "usage": None,
    }
    rate_limited = {
        "type": "error",
        "code": "rate_limit_exceeded",
        "message": "Rate limit reached for gpt-4o-mini. Please try again later.",
        "param": None,
    }
    fixtures = {
        "incomplete_max_tokens": [*head, *some, *incomplete],
        "refusal": refusal,
        "failed": [*head, *deltas[:3], {"type": "response.failed", "response": failed_response}],
        "error_event": [*head, *deltas[:3], rate_limited],
    }
    for name, fixture in fixtures.items():
        (directory / f"{name}.txt").write_text(to_sse(numbered(fixture)))


def derive_anthropic(directory: Path = FIXTURES / "anthropic") -> None:
    """Failure fixtures edited from the recorded `completed.txt`."""
    events = parse_sse((directory / "completed.txt").read_text())
    first_delta = next(i for i, e in enumerate(events) if e["type"] == "content_block_delta")
    head, deltas = events[:first_delta], [e for e in events if e["type"] == "content_block_delta"]
    last = {e["type"]: e for e in events[first_delta:]}
    some = deltas[: len(deltas) // 2]

    def stopped(reason: str, sent: list[Event], details: Event | None = None) -> list[Event]:
        message_delta = copy.deepcopy(last["message_delta"])
        message_delta["delta"] |= {"stop_reason": reason, "stop_details": details}
        return [*head, *sent, last["content_block_stop"], message_delta, last["message_stop"]]

    def midstream(kind: str, message: str) -> list[Event]:
        # The API sends `event: error` inside the 200 stream; the SDK raises it as APIStatusError.
        return [*head, *deltas[:3], {"type": "error", "error": {"type": kind, "message": message}}]

    refusal = {"type": "refusal", "category": "general_harms", "explanation": None}
    fixtures = {
        "max_tokens": stopped("max_tokens", some),
        "context_window_exceeded": stopped("model_context_window_exceeded", some),
        "refusal": stopped("refusal", deltas[:3], refusal),
        "overloaded_midstream": midstream("overloaded_error", "Overloaded"),
        "rate_limit_midstream": midstream("rate_limit_error", "Rate limited"),
    }
    for name, fixture in fixtures.items():
        (directory / f"{name}.txt").write_text(to_sse(fixture))


async def post_sse(url: str, body: dict[str, Any], headers: dict[str, str]) -> str:  # JSON body
    async with (
        httpx2.AsyncClient(timeout=60) as client,
        client.stream("POST", url, json=body, headers=headers) as response,
    ):
        raw = (await response.aread()).decode()
    if response.status_code != 200:
        sys.exit(f"{url} returned HTTP {response.status_code}: {raw}")
    return raw


def save(provider: str, events: list[Event]) -> Path:
    directory = FIXTURES / provider
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "completed.txt").write_text(to_sse(events))
    return directory


async def record_openai() -> None:
    settings = Settings(llm_provider="openai", llm_model=OPENAI_MODEL, llm_fallbacks="")
    ensure_budget(ESTIMATE_USD["openai"])
    body = openai_body(SYSTEM, TRANSCRIPT, temperature=settings.llm_temperature)
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    raw = await post_sse(OPENAI_URL, body, headers)

    events = parse_sse(IDS.sub(lambda m: f'"{m[1]}_fixture"', raw))
    terminal = events[-1]
    usage = (terminal.get("response") or {}).get("usage") or {}
    cost = cost_usd(
        OPENAI_MODEL,
        Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cached_input_tokens=usage.get("input_tokens_details", {}).get("cached_tokens", 0),
        ),
    )
    spent = ESTIMATE_USD["openai"] if cost is None or not usage else cost
    record_spend("record-sse-fixture", spent)
    print(f"{terminal['type']}: {len(events)} events, usage {usage}, cost ${spent:.6f}")
    if terminal["type"] != "response.completed":
        sys.exit("The recording did not complete; fixtures left unchanged.")
    derive_openai(save("openai", numbered(events)))


async def record_anthropic() -> None:
    settings = Settings(llm_provider="anthropic", llm_model=ANTHROPIC_MODEL, llm_fallbacks="")
    ensure_budget(ESTIMATE_USD["anthropic"])
    body = anthropic_body(SYSTEM, TRANSCRIPT, temperature=settings.llm_temperature)
    headers = {"x-api-key": settings.api_key, "anthropic-version": ANTHROPIC_VERSION}
    raw = await post_sse(ANTHROPIC_URL, body, headers)

    events = parse_sse(IDS.sub(lambda m: f'"{m[1]}_fixture"', raw))
    start: Event = next((e["message"]["usage"] for e in events if e["type"] == "message_start"), {})
    delta: Event = next((e for e in events if e["type"] == "message_delta"), {})
    # `message_delta` usage is cumulative and overwrites; absent (null) fields keep the start's.
    usage = start | {k: v for k, v in (delta.get("usage") or {}).items() if v is not None}
    read = usage.get("cache_read_input_tokens") or 0
    written = usage.get("cache_creation_input_tokens") or 0
    cost = cost_usd(
        ANTHROPIC_MODEL,
        Usage(
            input_tokens=usage.get("input_tokens", 0) + read + written,
            output_tokens=usage.get("output_tokens", 0),
            cached_input_tokens=read,
            cache_write_tokens=written,
        ),
    )
    spent = ESTIMATE_USD["anthropic"] if cost is None or not delta else cost
    record_spend("record-sse-fixture", spent)
    stop_reason = (delta.get("delta") or {}).get("stop_reason")
    print(f"{events[-1]['type']} ({stop_reason}): {len(events)} events, usage {usage}")
    print(f"cost ${spent:.6f}")
    if events[-1]["type"] != "message_stop" or stop_reason != "end_turn":
        sys.exit("The recording did not complete; fixtures left unchanged.")
    derive_anthropic(save("anthropic", events))


RECORDERS = {"openai": record_openai, "anthropic": record_anthropic}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in RECORDERS:
        sys.exit(f"usage: python -m scripts.record_sse_fixture {{{','.join(RECORDERS)}}}")
    asyncio.run(RECORDERS[sys.argv[1]]())
