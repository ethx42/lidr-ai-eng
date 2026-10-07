"""Record a raw provider SSE body as a unit-test fixture (live, budget-guarded).

`make record-cassettes SSE=openai` streams one tiny request with the JSON body `OpenAIProvider`
sends, saves the events to tests/fixtures/sse/openai/completed.txt (ids replaced, order kept)
and derives the failure fixtures from that recording.
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
from app.services.providers.openai_provider import text_format
from app.services.providers.profiles import get_profile, request_params
from scripts.live_budget import ensure_budget, record_spend

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sse"
OPENAI_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-4o-mini"
MAX_OUTPUT_TOKENS = 800
CACHE_KEY = "record-sse-fixture"
ESTIMATE_USD = 0.002
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
        get_profile(MODEL, "openai"),
        temperature=temperature,
        reasoning_effort=None,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return {
        "model": MODEL,
        "instructions": system,
        "input": user,
        "store": False,
        "prompt_cache_key": CACHE_KEY,
        "text": {"format": text_format(EstimationBreakdown)},
        "stream_options": {"include_obfuscation": False},
        "stream": True,
        **params,
    }


def parse_sse(text: str) -> list[Event]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def to_sse(events: list[Event]) -> str:
    renumbered = [{**event, "sequence_number": n} for n, event in enumerate(events)]
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for e in renumbered
    )


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
        (directory / f"{name}.txt").write_text(to_sse(fixture))


async def record_openai() -> None:
    settings = Settings(llm_provider="openai", llm_model=MODEL)
    ensure_budget(ESTIMATE_USD)
    body = openai_body(SYSTEM, TRANSCRIPT, temperature=settings.llm_temperature)
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    async with (
        httpx2.AsyncClient(timeout=60) as client,
        client.stream("POST", OPENAI_URL, json=body, headers=headers) as response,
    ):
        raw = (await response.aread()).decode()
    if response.status_code != 200:
        sys.exit(f"OpenAI returned HTTP {response.status_code}: {raw}")

    events = parse_sse(IDS.sub(lambda m: f'"{m[1]}_fixture"', raw))
    terminal = events[-1]
    usage = (terminal.get("response") or {}).get("usage") or {}
    cost = cost_usd(
        MODEL,
        Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cached_input_tokens=usage.get("input_tokens_details", {}).get("cached_tokens", 0),
        ),
    )
    spent = ESTIMATE_USD if cost is None or not usage else cost
    record_spend("record-sse-fixture", spent)
    print(f"{terminal['type']}: {len(events)} events, usage {usage}, cost ${spent:.6f}")
    if terminal["type"] != "response.completed":
        sys.exit("The recording did not complete; fixtures left unchanged.")

    directory = FIXTURES / "openai"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "completed.txt").write_text(to_sse(events))
    derive_openai(directory)


RECORDERS = {"openai": record_openai}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in RECORDERS:
        sys.exit(f"usage: python -m scripts.record_sse_fixture {{{','.join(RECORDERS)}}}")
    asyncio.run(RECORDERS[sys.argv[1]]())
