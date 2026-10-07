# Session 3 (`pre-session-03`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Orchestration rules (order, parallel tracks, gates, budget) live in `docs/catch-up/HANDOFF.md`.

**Goal:** A production-grade conversational client (Next.js) that streams structured estimates token by token from the AI service, plus the session 3 live-class layer: provider fallback, exact-match cache, cost and streaming observability.

**Architecture:** Providers stream raw JSON deltas through a `FallbackProvider`; the service turns accumulated text into throttled partial snapshots (jiter) and finally a validated `EstimateResponse`; FastAPI's native SSE carries `status/partial/result/error`; a Next.js BFF proxies the stream to the browser; Docker Compose runs `web`, `ai-service`, `redis`, with only `web` public.

**Tech Stack:** Python 3.12, FastAPI 0.141.1 (native SSE), openai 3.19.0, anthropic 1.8.0, jiter 0.17, redis-py 8.1 asyncio, fakeredis; Next.js App Router + TypeScript + Tailwind v4 + shadcn/ui, eventsource-parser, openapi-typescript/openapi-fetch, Vitest, Playwright + axe; Docker Compose v5.

**Spec:** `docs/catch-up/spec.md` §5 (and §2–§4, §8, §9). Brief: `~/Downloads/Sesion 3 ✍️ Ejercicio - Wrapper de interfaz conversacional 🔴 _ AI Engineering 2026_09.pdf`. Library facts: `.claude/stack.md` (sections dated 2026-10-06 are verified for this plan).

## Global Constraints

- Branch `pre-session-03` (cut from `main`, already contains `docs/catch-up/`). Never commit to `main`, never force-push, never `git reset --hard`, never `rm -rf`.
- English everywhere. Conventional commits, one per task. `make check` green before each commit.
- Never read, print or commit `.env`. `.env.example` is read with `git show HEAD:.env.example` and rewritten via a shell heredoc (a permission rule blocks the Read tool on `.env*`).
- Tests never call real LLMs. Live calls only through `make smoke-live`, `make record-cassettes`, `make eval`, all guarded by `scripts/live_budget.py` (`LIVE_BUDGET_USD`, default 5; ledger `docs/catch-up/spend.jsonl`). Live models: `gpt-4o-mini`, `claude-haiku-4-5` only.
- **Never use the SDKs' parsing stream helpers** (`responses.stream(text_format=…)`, `messages.stream(output_format=…)`): they raise `ValidationError` mid-stream before the stop condition is readable. Send the schema raw and validate the final text (verified, `.claude/stack.md`).
- SSE: 4xx-capable checks live in dependencies (once streaming starts the status is 200); errors inside the generator become an `error` event; never swallow `CancelledError`; awaited cleanup is shielded and bounded.
- Python dependencies are added with `uv add` (lockfile updated); web dependencies with `pnpm add` inside `web/`.

## Review Focus

1. Client closes the tab mid-stream → the upstream LLM stream is closed within 1 s, nothing is cached, `outcome=cancelled` is logged — Task 5 (in-process uvicorn test).
2. Primary provider times out before the first token → fallback serves the request and the UI shows a "Switched to Anthropic" status; primary fails *after* tokens were sent → an `error` event, never a mixed answer — Task 14.
3. Redis down or slow (blackholed) → requests still succeed with ≤ 0.5 s added latency and `cache=error` in logs — Task 15.
4. A malformed or empty partial snapshot never crashes the stream or the UI (partial objects with missing fields render as skeletons) — Tasks 3 and 9.
5. A transcript at exactly the limit and one char over → 200 stream vs 422 JSON (never a 200 with an empty body) — Task 5.

## Execution order and tracks

Thin end-to-end slice first, then deepen (see `HANDOFF.md`):

1. Slice (sequential): Task 1 → 2 → 3 → 4 → 5.
2. Two parallel tracks in separate git worktrees, merged back into `pre-session-03`:
   - **Track A (AI service):** Tasks 12 → 13 → 14 → 15 → 16.
   - **Track W (web):** Tasks 6 → 7 → 8 → 9 → 10 → 11.
3. Join (sequential): Tasks 17 → 18 → 19 → 20.

---

### Task 1: Bootstrap — gate, spend guard, agent guide

**Files:**
- Create: `scripts/live_budget.py`, `scripts/gate.sh`, `docs/catch-up/spend.jsonl` (empty)
- Modify: `Makefile` (`gate`), `AGENTS.md` (catch-up section), `.gitignore` (nothing to add unless needed)
- Test: `tests/unit/test_live_budget.py`

**Interfaces:**
- Produces: `live_budget.ensure_budget(estimated_usd: float, *, ledger: Path = LEDGER, budget: float | None = None) -> float` (returns remaining; raises `BudgetExceeded`), `live_budget.record_spend(command: str, cost_usd: float, *, ledger: Path = LEDGER) -> None`, `live_budget.total_spent(ledger: Path = LEDGER) -> float`; `make gate BRANCH=<name>`.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_live_budget.py
import pytest

from scripts.live_budget import BudgetExceeded, ensure_budget, record_spend, total_spent


def test_records_and_sums(tmp_path) -> None:
    ledger = tmp_path / "spend.jsonl"
    record_spend("smoke", 0.012, ledger=ledger)
    record_spend("eval", 0.020, ledger=ledger)
    assert total_spent(ledger) == pytest.approx(0.032)


def test_refuses_when_estimate_exceeds_remaining(tmp_path) -> None:
    ledger = tmp_path / "spend.jsonl"
    record_spend("eval", 4.99, ledger=ledger)
    with pytest.raises(BudgetExceeded):
        ensure_budget(0.05, ledger=ledger, budget=5.0)
    assert ensure_budget(0.005, ledger=ledger, budget=5.0) == pytest.approx(0.01)


def test_budget_defaults_to_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_BUDGET_USD", "0.01")
    with pytest.raises(BudgetExceeded):
        ensure_budget(0.02, ledger=tmp_path / "spend.jsonl")
```

(`scripts/` needs an `__init__.py`; add `scripts` to the mypy and pytest paths if they are not already covered.)

- [ ] **Step 2: Implement** — JSON lines `{"ts", "command", "cost_usd"}`; `BudgetExceeded(RuntimeError)` with remaining/estimate in the message; default budget `float(os.environ.get("LIVE_BUDGET_USD", "5"))`. Guard the existing live eval too: `evals/run_eval.py` `main` calls `ensure_budget(0.10)` before running and, after the run, `record_spend("eval", cost)` with the cost summed from each case's usage (use `app.services.pricing.cost_usd` once Task 2 exists; until then record 0.0 and note it).

- [ ] **Step 3: Gate script** — `scripts/gate.sh <branch>` runs, stopping at the first failure and printing each stage name: `make check`; `docker compose up --build --wait` then `make e2e` then `docker compose down`; `git diff --exit-code contracts/openapi.json` after `make openapi`; the branch's section of `docs/catch-up/PROGRESS.md` (from `## <branch>` to the next `## `) contains no `[ ]` and no `[!]` lines; `git fetch origin <branch>` and `git rev-parse HEAD` == `git rev-parse origin/<branch>`. On success it prints exactly `GATE PASS <branch> <sha>`. Makefile: `gate: ; bash scripts/gate.sh $(BRANCH)`. (Stages that need later tasks fail until those tasks exist; the gate is only expected to pass at branch close.)

- [ ] **Step 4: AGENTS.md** — add a "Catch-up mode (pre-session-0N branches)" section: plans live in `docs/catch-up/`; OpenSpec-lite per spec D11 (no change folders; update `openspec/specs/*` in place at branch close); `make gate` defines done.

- [ ] **Step 5: `make check`; commit** `chore(catch-up): spend guard, branch gate and agent guide`

---

### Task 2: Streaming contract, pricing and call metrics

**Files:**
- Modify: `app/services/providers/base.py`, `app/config.py` (`Provider` adds `"replay"`), `app/schemas/estimation.py`, `app/services/llm_service.py`, `app/services/providers/openai_provider.py`, `anthropic_provider.py` (fill `provider`/`model`), `tests/fakes.py`, `app/main.py` (custom OpenAPI)
- Create: `app/schemas/stream.py`, `app/services/pricing.py`, `scripts/export_openapi.py`, `contracts/openapi.json`
- Test: `tests/unit/test_pricing.py`, `tests/unit/test_llm_service.py` (metrics), `tests/test_openapi_snapshot.py`

**Interfaces:**
- Produces (exact names used by every later task):

```python
# app/services/providers/base.py
@dataclass(frozen=True)
class LLMResult[M: BaseModel]:
    parsed: M
    usage: Usage
    latency_ms: int
    provider: Provider
    model: str
    attempts: int = 1
    fallback_used: bool = False

@dataclass(frozen=True)
class TextDelta:
    text: str       # new text
    snapshot: str   # all text received so far

@dataclass(frozen=True)
class ProviderSwitch:
    provider: Provider
    model: str
    cause: str | None

type StreamEvent[M: BaseModel] = TextDelta | ProviderSwitch | LLMResult[M]

class LLMProvider(Protocol):
    name: Provider
    model: str
    async def generate(self, *, system: str, user: str, schema: type[T], cache_key: str) -> LLMResult[T]: ...
    def stream(self, *, system: str, user: str, schema: type[T], cache_key: str) -> AsyncIterator[StreamEvent[T]]: ...
    async def aclose(self) -> None: ...

# app/schemas/estimation.py
class CallMetrics(BaseModel):
    latency_ms: int
    ttft_ms: int | None = None
    cost_usd: float | None = None
    cache_hit: bool = False
    fallback_used: bool = False
    attempts: int = 1
# EstimateResponse gains: metrics: CallMetrics ; provider: Literal["openai", "anthropic", "replay"]

# app/schemas/stream.py
class StatusEvent(BaseModel):
    phase: Literal["calling_llm", "fallback", "validating", "cache_hit"]
    provider: str | None = None
    model: str | None = None

class PartialEvent(BaseModel):
    seq: int
    breakdown: dict[str, Any]

class ErrorEvent(BaseModel):
    code: str
    message: str
    retryable: bool
    request_id: str

# app/services/pricing.py
PRICES_CHECKED = "2026-10-06"
def cost_usd(model: str, usage: Usage) -> float | None: ...
```

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_pricing.py
import pytest

from app.schemas.estimation import Usage
from app.services.pricing import cost_usd


def test_openai_cached_tokens_billed_at_cached_rate() -> None:
    usage = Usage(input_tokens=10_000, output_tokens=1_000, cached_input_tokens=8_000, cache_write_tokens=0)
    # (2000*0.15 + 8000*0.075 + 1000*0.60) / 1e6
    assert cost_usd("gpt-4o-mini", usage) == pytest.approx(0.0015)


def test_anthropic_dated_snapshot_matches_by_prefix() -> None:
    usage = Usage(input_tokens=9_000, output_tokens=1_000, cached_input_tokens=6_000, cache_write_tokens=2_000)
    # uncached 1000*1.00 + read 6000*0.10 + write 2000*1.25 + out 1000*5.00
    assert cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(0.0091)


def test_unknown_model_has_no_cost() -> None:
    assert cost_usd("mystery-model", Usage(input_tokens=1, output_tokens=1)) is None
```

```python
# tests/unit/test_llm_service.py (add)
async def test_blocking_response_carries_metrics(service_with_fake) -> None:
    response = await service_with_fake.estimate(request())
    assert response.metrics.cache_hit is False
    assert response.metrics.attempts == 1
    assert response.metrics.ttft_ms is None
    assert response.provider == "openai" and response.model == "fake-model"
```

```python
# tests/test_openapi_snapshot.py
import json
from pathlib import Path

from app.main import create_app


def test_contract_snapshot_is_current() -> None:
    current = create_app().openapi()
    committed = json.loads(Path("contracts/openapi.json").read_text())
    assert current == committed, "Run `make openapi` and commit contracts/openapi.json"


def test_stream_event_models_are_in_the_contract() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert {"StatusEvent", "PartialEvent", "ErrorEvent", "EstimateResponse"} <= set(schemas)
```

- [ ] **Step 2: Run, confirm failures.**

- [ ] **Step 3: Implement**
  - `pricing.py`: `@dataclass(frozen=True) class Price(input, cached_input, cache_write, output)` per 1M tokens; `PRICES = {"gpt-4o-mini": Price(0.15, 0.075, 0.15, 0.60), "claude-haiku-4-5": Price(1.00, 0.10, 1.25, 5.00)}` with a comment citing the two pricing URLs and `PRICES_CHECKED`; match the longest key that is a prefix of the model id; `uncached = max(input - cached - cache_write, 0)` (both providers report `input_tokens` as the total in this project); round to 6 decimals.
  - Providers fill `provider=self.name, model=self.model` in `LLMResult`.
  - `EstimationService` builds `metrics=CallMetrics(latency_ms=..., cost_usd=cost_usd(result.model, result.usage), attempts=result.attempts, fallback_used=result.fallback_used)` and uses `result.provider`/`result.model` in the response and the `llm_call` log.
  - `FakeProvider` gets `stream()` yielding the JSON of its result in 3 chunks (`TextDelta`s with growing snapshots) then the `LLMResult`; records `closed_streams` when its generator is closed early (in a `finally`).
  - Custom OpenAPI in `create_app`: wrap `app.openapi` so the generated schema includes `StatusEvent`, `PartialEvent`, `ErrorEvent` under `components.schemas` (use `pydantic.json_schema.models_json_schema([(M, "serialization") ...], ref_template="#/components/schemas/{model}")` and merge `$defs`), cached on `app.openapi_schema`.
  - `scripts/export_openapi.py` writes `create_app().openapi()` to `contracts/openapi.json` with `indent=2, sort_keys=True` and a trailing newline; Makefile `openapi: ; uv run python -m scripts.export_openapi`. The snapshot test makes `make check` fail when stale.

- [ ] **Step 4: `make openapi && make check`; commit** `feat(contract): streaming types, call metrics, pricing and an OpenAPI snapshot`

---

### Task 3: Partial snapshots from streamed JSON

**Files:**
- Create: `app/services/streaming.py`
- Modify: `pyproject.toml` (`uv add "jiter>=0.17.0"`)
- Test: `tests/unit/test_streaming.py`

**Interfaces:**
- Produces:

```python
class PartialSnapshotter:
    def __init__(self, *, min_interval: float = 0.1, clock: Callable[[], float] = time.monotonic) -> None: ...
    def feed(self, snapshot: str) -> PartialEvent | None: ...    # throttled
    def flush(self, snapshot: str) -> PartialEvent | None: ...   # ignores the throttle; emits only if changed
```

- [ ] **Step 1: Failing tests**

```python
from app.services.streaming import PartialSnapshotter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_emits_partial_objects_with_trailing_strings() -> None:
    s = PartialSnapshotter(clock=Clock())
    event = s.feed('{"project_name": "Yoga Bo')
    assert event is not None and event.seq == 1
    assert event.breakdown == {"project_name": "Yoga Bo"}


def test_throttles_within_interval_and_flush_emits_latest() -> None:
    clock = Clock()
    s = PartialSnapshotter(min_interval=0.1, clock=clock)
    assert s.feed('{"a": "x') is not None
    clock.now = 0.05
    assert s.feed('{"a": "xy') is None
    flushed = s.flush('{"a": "xyz"}')
    assert flushed is not None and flushed.breakdown == {"a": "xyz"} and flushed.seq == 2


def test_unchanged_snapshot_is_not_reemitted() -> None:
    clock = Clock()
    s = PartialSnapshotter(clock=clock)
    s.feed('{"a": 1, ')
    clock.now = 1
    assert s.feed('{"a": 1, "b') is None   # same dict: {"a": 1}


def test_empty_whitespace_and_non_object_snapshots_are_ignored() -> None:
    s = PartialSnapshotter(clock=Clock())
    assert s.feed("") is None
    assert s.feed("   ") is None
    assert s.feed('["x"') is None
    assert s.feed("garbage {") is None
```

- [ ] **Step 2: Implement** — `jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")` inside `try/except ValueError`; only `dict` results; compare with the last emitted dict; `seq` increments per emitted event; `feed` returns `None` when `clock() - last_emit < min_interval`.
- [ ] **Step 3: `make check`; commit** `feat(streaming): throttled partial snapshots from streamed JSON`

---

### Task 4: Replay provider

**Files:**
- Create: `app/services/providers/replay_provider.py`, `tests/cassettes/.gitkeep`
- Modify: `app/config.py` (`replay_cassette_dir: Path = Path("tests/cassettes")`, `replay_speed: float = Field(default=1.0, ge=0)`; `replay` needs no API key), `app/services/providers/factory.py`
- Test: `tests/unit/providers/test_replay_provider.py`

**Interfaces:**
- Produces: `ReplayProvider(*, cassette_dir: Path, fallback: Sequence[EstimationBreakdown], speed: float, chunk_chars: int = 24, chunk_delay: float = 0.02)`; `cassette_key(system: str, user: str) -> str` = `sha256(f"{system}\x00{user}")` hex (session 4's `RenderedPrompt.sha256` must use the same formula); cassette file `tests/cassettes/<key>.json`:

```json
{"key": "<sha>", "provider": "openai", "model": "gpt-4o-mini", "recorded_at": "2026-10-06T23:00:00Z",
 "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0},
 "chunks": [[0, "{\"project_"], [35, "name\": \"Yoga"]]}
```

(`chunks` = `[elapsed_ms_since_first_chunk, text]`.)

- [ ] **Step 1: Failing tests**

```python
async def test_replays_cassette_text_and_timing(tmp_path) -> None:
    breakdown_json = breakdown().model_dump_json()
    key = cassette_key("S", "U")
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "key": key, "provider": "openai", "model": "gpt-4o-mini", "recorded_at": "x",
        "usage": {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 0, "cache_write_tokens": 0},
        "chunks": [[0, breakdown_json[:20]], [10, breakdown_json[20:]]],
    }))
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], speed=0)
    events = [e async for e in p.stream(system="S", user="U", schema=EstimationBreakdown, cache_key="k")]
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert "".join(d.text for d in deltas) == breakdown_json
    assert deltas[-1].snapshot == breakdown_json
    final = events[-1]
    assert isinstance(final, LLMResult) and final.provider == "replay" and final.usage.input_tokens == 10


async def test_synthesises_a_stream_without_cassette(tmp_path) -> None:
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], speed=0)
    events = [e async for e in p.stream(system="S", user="other", schema=EstimationBreakdown, cache_key="k")]
    assert len([e for e in events if isinstance(e, TextDelta)]) > 3
    assert isinstance(events[-1], LLMResult)


async def test_generate_returns_the_same_parsed_result(tmp_path) -> None:
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], speed=0)
    result = await p.generate(system="S", user="U", schema=EstimationBreakdown, cache_key="k")
    assert result.parsed == breakdown()
```

- [ ] **Step 2: Implement** — fallback chosen by `int(key, 16) % len(fallback)` (deterministic); synthetic chunks of `chunk_chars` with `chunk_delay * speed` sleeps; cassette sleeps are `(t_i - t_{i-1}) / 1000 * speed`; usage zeros for synthetic; the factory builds `ReplayProvider` for `LLM_PROVIDER=replay` with `fallback=[ref.estimation for ref in REFERENCE_ESTIMATIONS]`.
- [ ] **Step 3: `make check`; commit** `feat(providers): replay provider for deterministic streams`

---

### Task 5: Streaming service, SSE endpoint and context endpoint (end-to-end slice)

**Files:**
- Modify: `app/services/llm_service.py`, `app/routers/estimations.py`, `app/observability.py` (new `llm_call` fields), `contracts/openapi.json`
- Test: `tests/unit/test_llm_service_stream.py`, `tests/api/test_estimate_stream.py`, `tests/api/test_stream_disconnect.py`, `tests/api/test_context.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: `EstimationService.estimate_stream(request: EstimateRequest) -> AsyncIterator[StatusEvent | PartialEvent | EstimateResponse]`; `POST /api/v1/estimate/stream` (spec §4.4); `GET /api/v1/context` → `ContextResponse{prompt_version: str, system_prompt: str, references: list[ReferenceView], chain: list[str]}` with `ReferenceView{size: str, meeting_summary: str, estimation: EstimationBreakdown}`; dependency alias `CheckedRequest = Annotated[EstimateRequest, Depends(checked_request)]` (length check) used by both estimate endpoints; `log_llm_call(..., stream: bool = False, ttft_ms: int | None = None, cost_usd: float | None = None, attempts: int = 1, fallback: bool = False, cache: str = "bypass")` (outcome adds `"cancelled"`).

- [ ] **Step 1: Failing service tests**

```python
async def test_stream_yields_status_partials_then_result(service_with_fake) -> None:
    items = [i async for i in service_with_fake.estimate_stream(request())]
    assert isinstance(items[0], StatusEvent) and items[0].phase == "calling_llm"
    partials = [i for i in items if isinstance(i, PartialEvent)]
    assert partials and [p.seq for p in partials] == sorted({p.seq for p in partials})
    assert isinstance(items[-1], EstimateResponse)
    assert items[-1].metrics.ttft_ms is not None
    assert sum(isinstance(i, EstimateResponse) for i in items) == 1


async def test_closing_the_stream_early_closes_the_provider_stream(service_with_slow_fake, slow_fake) -> None:
    gen = service_with_slow_fake.estimate_stream(request())
    await anext(gen)            # status
    await anext(gen)            # first partial
    await gen.aclose()
    assert slow_fake.closed_streams == 1


async def test_provider_error_propagates_as_llm_error(service_with_failing_fake) -> None:
    with pytest.raises(UpstreamUnavailable):
        [i async for i in service_with_failing_fake.estimate_stream(request())]
```

- [ ] **Step 2: Failing API tests**

```python
def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        events.append((fields.get("event", "message"), json.loads(fields["data"])))
    return events


def test_stream_contract(client) -> None:
    with client.stream("POST", "/api/v1/estimate/stream", json={"transcription": TRANSCRIPT}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.read().decode())
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "result"
    assert names.count("result") + names.count("error") == 1
    assert "partial" in names


def test_over_limit_is_422_json_not_a_stream(client_with_limit_10) -> None:
    r = client_with_limit_10.post("/api/v1/estimate/stream", json={"transcription": "x" * 11})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_at_limit_streams(client_with_limit_10) -> None:
    r = client_with_limit_10.post("/api/v1/estimate/stream", json={"transcription": "x" * 10})
    assert r.status_code == 200


def test_upstream_failure_becomes_an_error_event(client_with_failing_provider) -> None:
    r = client_with_failing_provider.post("/api/v1/estimate/stream", json={"transcription": TRANSCRIPT})
    events = parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "upstream_unavailable" and events[-1][1]["retryable"] is True
    assert events[-1][1]["request_id"] == r.headers["x-request-id"]
```

```python
# tests/api/test_stream_disconnect.py — real socket, still offline
async def test_client_disconnect_closes_upstream(unused_tcp_port, slow_fake, settings) -> None:
    app = create_app(settings=settings, provider_factory=lambda _: slow_fake)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        async with httpx2.AsyncClient() as http:
            async with http.stream("POST", f"http://127.0.0.1:{unused_tcp_port}/api/v1/estimate/stream", json={"transcription": TRANSCRIPT}) as r:
                async for line in r.aiter_lines():
                    if line == "event: partial":
                        break
        await asyncio.wait_for(slow_fake.stream_closed.wait(), timeout=1)
    finally:
        server.should_exit = True
        await task
```

```python
# tests/api/test_context.py
def test_context_exposes_prompt_and_references(client) -> None:
    body = client.get("/api/v1/context").json()
    assert body["prompt_version"] and "<reference_estimations>" in body["system_prompt"]
    assert len(body["references"]) == 3 and body["chain"]
```

`slow_fake`: a `FakeProvider` variant whose `stream()` yields one delta, then awaits an `asyncio.Event` that never fires, and sets `stream_closed` in its `finally`. Disconnect detection needs a real server because in-process transports buffer the whole body (verified).

- [ ] **Step 3: Implement the service**

```python
async def estimate_stream(self, request: EstimateRequest) -> AsyncIterator[StatusEvent | PartialEvent | EstimateResponse]:
    user = build_user_message(request.transcription, request.output_language)
    start = time.perf_counter()
    snapshotter = PartialSnapshotter()
    snapshot, ttft_ms, result = "", None, None
    yield StatusEvent(phase="calling_llm", provider=self.provider.name, model=self.provider.model)
    try:
        async with aclosing(self.provider.stream(system=self.prompt.system_text, user=user, schema=EstimationBreakdown, cache_key=self.cache_key)) as events:
            async for event in events:
                match event:
                    case TextDelta():
                        ttft_ms = ttft_ms or _ms_since(start)
                        snapshot = event.snapshot
                        if partial := snapshotter.feed(snapshot):
                            yield partial
                    case ProviderSwitch():
                        yield StatusEvent(phase="fallback", provider=event.provider, model=event.model)
                    case LLMResult():
                        result = event
    except LLMError as exc:
        self._log_call(None, _ms_since(start), exc, stream=True, ttft_ms=ttft_ms)
        raise
    except asyncio.CancelledError:
        self._log_cancelled(_ms_since(start), ttft_ms)   # sync logging only: no await while cancelled
        raise
    if result is None:
        raise InvalidModelOutput(reason="no_final_result")
    if partial := snapshotter.flush(snapshot):
        yield partial
    yield StatusEvent(phase="validating")
    yield self._respond(result, request, ttft_ms=ttft_ms)   # shared with estimate(): enrich, grounding, render, metrics, log
```

Refactor `estimate()` to use the same `_respond(...)`. `self.cache_key` is the existing `f"estimator-{version}"` routing key.

- [ ] **Step 4: Implement the endpoints**

```python
def checked_request(body: EstimateRequest, settings: SettingsDep) -> EstimateRequest:
    limit = settings.max_transcription_chars
    if len(body.transcription) > limit:
        raise RequestValidationError([{"loc": ("body", "transcription"), "msg": f"Transcription exceeds {limit} characters.", "type": "string_too_long"}])
    return body

CheckedRequest = Annotated[EstimateRequest, Depends(checked_request)]


@router.post("/estimate/stream", response_class=EventSourceResponse, summary="Stream an estimate as Server-Sent Events", responses={...})
async def estimate_stream(body: CheckedRequest, service: ServiceDep) -> AsyncIterator[ServerSentEvent]:
    try:
        async for item in service.estimate_stream(body):
            match item:
                case StatusEvent():
                    yield ServerSentEvent(event="status", data=item)
                case PartialEvent():
                    yield ServerSentEvent(event="partial", data=item, id=str(item.seq))
                case EstimateResponse():
                    yield ServerSentEvent(event="result", data=item)
    except LLMError as exc:
        yield ServerSentEvent(event="error", data=ErrorEvent(code=exc.code, message=exc.message, retryable=exc.status_code in (429, 503), request_id=request_id_var.get()))
    except Exception:
        logger.exception("stream_failed")
        yield ServerSentEvent(event="error", data=ErrorEvent(code="internal_error", message="Internal server error.", retryable=False, request_id=request_id_var.get()))
```

Document the event types in `responses={200: {"content": {"text/event-stream": {"schema": {"oneOf": [{"$ref": "#/components/schemas/StatusEvent"}, ...]}}}}}`. The blocking endpoint switches to `CheckedRequest` too. FastAPI already sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` and sends `: ping` every 15 s (verified).

- [ ] **Step 5: `make openapi && make check`; commit** `feat(api): stream estimates over SSE with partial snapshots; context endpoint`

**Slice checkpoint:** with `LLM_PROVIDER=replay`, `uv run uvicorn app.main:app` + `curl -N -X POST localhost:8000/api/v1/estimate/stream -H 'content-type: application/json' -d '{"transcription":"..."}'` shows `status → partial… → result`. Paste that output in the transcript.

---

### Task 6: Web scaffold, design tokens and typed client

**Files:**
- Create: `web/` (Next.js app; exact create command and flags in `.claude/stack.md` "Next.js"), `web/components.json`, `web/src/app/globals.css` (tokens), `web/src/lib/ai-service/schema.d.ts` (generated), `web/src/lib/ai-service/env.ts`, `web/vitest.config.ts`, `web/src/content/samples/{course-meeting.md,clinic-portal.md,vague-marketplace.md}`
- Modify: `Makefile` (`web-install`, `web-types`, `web-check`; `check` runs `web-check` after the Python steps), `.gitignore` (`web/node_modules`, `web/.next`, `web/test-results`, `web/playwright-report`)
- Test: `web/src/lib/ai-service/env.test.ts`, `tests/test_web_samples.py`

**Interfaces:**
- Produces: `pnpm -C web lint|typecheck|test`; `web/src/lib/ai-service/schema.d.ts` from `contracts/openapi.json` via `openapi-typescript` (script `pnpm -C web gen:types`; `make web-types`); `serverEnv(): { AI_SERVICE_URL: string }` (imports `server-only`, throws a clear error when missing); samples are byte-identical copies of `data/transcripts/course-meeting.md`, `evals/golden/02-medium-clinic-portal.md`, `evals/golden/03-vague-marketplace.md` with front matter stripped.

- [ ] **Step 1: Scaffold** with the verified non-interactive command (App Router, TypeScript strict, Tailwind v4, `src/` dir, pnpm, import alias `@/*`); `next.config.ts` with `output: "standalone"`; add shadcn/ui via its CLI (`init`, then `add button card badge tabs tooltip hover-card skeleton separator scroll-area sheet textarea toggle-group dropdown-menu sonner resizable table`); add `eventsource-parser`, `openapi-typescript` (dev), `openapi-fetch`, `server-only`, `zod`, `react-hook-form`, `@hookform/resolvers`; Vitest + Testing Library + jsdom; lint per the verified recommendation.
- [ ] **Step 2: Design tokens** — use the `frontend-design` skill constrained to spec §8 (sober enterprise: neutral palette with one accent, semantic state colours, type scale 12/14/16/20/24, 4/8 px spacing, radius small, light + dark via CSS variables, `font-variant-numeric: tabular-nums` utility for numbers, focus ring token, motion tokens ≤ 150 ms and zero under `prefers-reduced-motion`). Record the chosen palette and type in a short comment block at the top of `globals.css`.
- [ ] **Step 3: Failing tests**

```ts
// web/src/lib/ai-service/env.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

describe("serverEnv", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("returns the AI service URL without a trailing slash", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000/");
    const { serverEnv } = await import("./env");
    expect(serverEnv().AI_SERVICE_URL).toBe("http://ai-service:8000");
  });
  it("fails loudly when missing", async () => {
    vi.stubEnv("AI_SERVICE_URL", "");
    const { serverEnv } = await import("./env");
    expect(() => serverEnv()).toThrow(/AI_SERVICE_URL/);
  });
});
```

```python
# tests/test_web_samples.py
from pathlib import Path

import pytest

from evals.run_eval import FRONT_MATTER

PAIRS = [
    ("data/transcripts/course-meeting.md", "web/src/content/samples/course-meeting.md"),
    ("evals/golden/02-medium-clinic-portal.md", "web/src/content/samples/clinic-portal.md"),
    ("evals/golden/03-vague-marketplace.md", "web/src/content/samples/vague-marketplace.md"),
]


@pytest.mark.parametrize(("source", "copy"), PAIRS)
def test_web_samples_match_their_sources(source: str, copy: str) -> None:
    expected = FRONT_MATTER.sub("", Path(source).read_text(encoding="utf-8"))
    assert Path(copy).read_text(encoding="utf-8") == expected
```

- [ ] **Step 4: Implement, `make check` (now includes `web-check`); commit** `feat(web): Next.js app with design tokens, typed AI-service client and samples`

---

### Task 7: BFF route handlers

**Files:**
- Create: `web/src/lib/ai-service/proxy.ts`, `web/src/app/api/estimate/stream/route.ts`, `web/src/app/api/context/route.ts`
- Test: `web/src/lib/ai-service/proxy.test.ts`, `web/src/app/api/estimate/stream/route.test.ts`

**Interfaces:**
- Produces: `proxySse(request: Request, upstreamPath: string, init?: { maxBodyBytes?: number }): Promise<Response>`; `proxyJson(request: Request, upstreamPath: string): Promise<Response>`. Browser-facing routes: `POST /api/estimate/stream`, `GET /api/context`.

- [ ] **Step 1: Failing tests**

```ts
// web/src/app/api/estimate/stream/route.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

describe("POST /api/estimate/stream", () => {
  beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("pipes the upstream SSE body unbuffered and passes the abort signal", async () => {
    const upstreamBody = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode("event: status\ndata: {}\n\n")); c.close(); } });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(upstreamBody, { headers: { "content-type": "text/event-stream" } }));
    const { POST } = await import("./route");
    const req = new Request("http://web/api/estimate/stream", { method: "POST", body: JSON.stringify({ transcription: "hi" }), headers: { "content-type": "application/json" } });
    const res = await POST(req);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://ai-service:8000/api/v1/estimate/stream");
    expect((init as RequestInit).signal).toBe(req.signal);
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    expect(res.headers.get("cache-control")).toMatch(/no-transform/);
    expect(await res.text()).toContain("event: status");
  });

  it("passes upstream 422 JSON through with its status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "invalid_request" } }, { status: 422 }));
    const { POST } = await import("./route");
    const res = await POST(new Request("http://web/api/estimate/stream", { method: "POST", body: "{}" }));
    expect(res.status).toBe(422);
    expect((await res.json()).error.code).toBe("invalid_request");
  });

  it("rejects oversized bodies before calling upstream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("./route");
    const res = await POST(new Request("http://web/api/estimate/stream", { method: "POST", body: "x".repeat(2_000_001) }));
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps an unreachable AI service to 503 with the project error shape", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const { POST } = await import("./route");
    const res = await POST(new Request("http://web/api/estimate/stream", { method: "POST", body: "{}" }));
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("upstream_unavailable");
  });
});
```

- [ ] **Step 2: Implement** — the upstream URL is built only from `serverEnv().AI_SERVICE_URL` + a fixed path (no client-controlled URL: SSRF guard); forward only `content-type`, `accept`, `x-request-id` (generate one with `crypto.randomUUID()` if absent); default max body 2 MB; success response headers: `content-type: text/event-stream; charset=utf-8`, `cache-control: no-cache, no-transform`, `x-accel-buffering: no`, `x-request-id` from upstream; route segment config per the verified Next.js guidance (dynamic, Node runtime, no compression on this route). Abort from the browser propagates through `request.signal`.
- [ ] **Step 3: `pnpm -C web test`, `make check`; commit** `feat(web): BFF route handlers proxying the AI service`

---

### Task 8: `useEstimateStream` hook

**Files:**
- Create: `web/src/hooks/use-estimate-stream.ts`, `web/src/lib/estimate/types.ts`, `web/src/lib/errors.ts`
- Test: `web/src/hooks/use-estimate-stream.test.ts`, `web/src/lib/errors.test.ts`

**Interfaces:**
- Consumes: generated `components["schemas"]` types: `EstimateRequest`, `EstimateResponse`, `StatusEvent`, `PartialEvent`, `ErrorEvent`, `EstimationBreakdown`.
- Produces:

```ts
export type DeepPartial<T> = T extends (infer U)[] ? DeepPartial<U>[] : T extends object ? { [K in keyof T]?: DeepPartial<T[K]> } : T;
export type PartialBreakdown = DeepPartial<EstimationBreakdown>;
export type Phase = StatusEvent["phase"];
export type StreamError = { code: string; message: string; retryable: boolean; requestId?: string };
export type StreamState =
  | { status: "idle" }
  | { status: "streaming"; phase: Phase; switchedTo?: string; partial: PartialBreakdown | null; startedAt: number }
  | { status: "done"; result: EstimateResponse }
  | { status: "error"; error: StreamError; partial: PartialBreakdown | null }
  | { status: "cancelled"; partial: PartialBreakdown | null };
export function useEstimateStream(endpoint?: string): { state: StreamState; start(body: EstimateRequest): void; stop(): void };
export function toUserMessage(error: StreamError): { title: string; action: "retry" | "shorten" | "wait" | "contact" };
```

- [ ] **Step 1: Failing tests** — mock `fetch` with a `ReadableStream` that emits SSE frames split across chunk boundaries (`"event: par"` + `"tial\ndata: {...}\n\n"`):
  - sequence `status` → `partial` (seq 1, 2) → `result` ends in `{status: "done"}` and intermediate renders expose `partial` from the latest `PartialEvent`;
  - an `error` event yields `{status: "error"}` and keeps the last partial;
  - `stop()` during streaming aborts the fetch (`signal.aborted === true`) and yields `{status: "cancelled"}` with the last partial;
  - HTTP 422 JSON yields `{status: "error", error.code: "invalid_request"}` without parsing SSE;
  - a stream that ends without a terminal event yields `{status: "error", code: "stream_interrupted", retryable: true}`;
  - `status{phase:"fallback", provider:"anthropic"}` sets `switchedTo: "anthropic"`;
  - unmount aborts an in-flight request.
  - `toUserMessage`: `upstream_rate_limited` → wait; `upstream_unavailable` → retry; `invalid_request` with `string_too_long` → shorten; `internal_error` → contact.
- [ ] **Step 2: Implement** — `fetch` with `AbortController`; parse with `res.body.pipeThrough(new TextDecoderStream()).pipeThrough(new EventSourceParserStream())` (verify import path in `.claude/stack.md`), consumed with a reader loop (not `for await`, for Safari); `JSON.parse` per event inside `try` (malformed frame → ignore); state updates batched per frame.
- [ ] **Step 3: `pnpm -C web test`, `make check`; commit** `feat(web): estimate streaming hook with cancellation and error mapping`

---

### Task 9: Estimate view (progressive rendering)

**Files:**
- Create: `web/src/components/estimate/{estimate-view.tsx,estimate-skeleton.tsx,totals-strip.tsx,requirements-list.tsx,tasks-table.tsx,range-bar.tsx,team-and-risks.tsx,open-questions.tsx,grounding-alert.tsx,confidence-badge.tsx,status-steps.tsx}`, `web/src/lib/estimate/format.ts`, `web/src/lib/estimate/fixtures.ts`
- Test: `web/src/components/estimate/estimate-view.test.tsx`, `web/src/lib/estimate/format.test.ts`

**Interfaces:**
- Produces: `<EstimateView data={PartialBreakdown | EnrichedBreakdown} grounding?={GroundingReport} streaming={boolean} activeRequirement?={string} onRequirementFocus?={(id: string | null) => void} />`; `<StatusSteps state={StreamState} />`; `formatHours(n: number): string` ("24.5 h"), `formatRange(lo, hi)`, `formatUsd(n)`.

- [ ] **Step 1: Failing tests**
  - Renders a full `EnrichedBreakdown` fixture: project name as the page's `h2`, totals strip (expected hours, range, duration, cost when present), requirements with their evidence in a hover card (keyboard focusable), tasks grouped by phase with `RangeBar` showing optimistic/likely/pessimistic (accessible label "Optimistic 8 h, likely 12 h, pessimistic 20 h"), team, risks with impact badges, open questions, confidence badge with rationale.
  - Renders partial fixtures without throwing: `{}`, `{project_name: "Yo"}`, `{tasks: [{id: "T1", name: "Back"}]}` (missing hours → skeleton cells), `{requirements: [{id: "R1"}]}`; sections not yet received render `EstimateSkeleton` blocks shaped like the final section; totals strip shows skeletons until the final result (totals are computed server-side).
  - Grounding: ungrounded requirement ids show ⚠ with text "Quote not found in the transcript"; tasks without valid basis show ⚠ in the table.
  - While `streaming`, the last-growing text is not announced; a single `aria-live="polite"` region announces "Estimate ready" when `streaming` turns false.
- [ ] **Step 2: Implement** with shadcn primitives; numbers right-aligned with `tabular-nums`; one `h2` per estimate, `h3` per section; section order matches the schema (summary → requirements → assumptions → open questions → tasks → team → risks → confidence) with the totals strip pinned under the title; no animation beyond skeleton pulse (disabled under reduced motion).
- [ ] **Step 3: `pnpm -C web test`, `make check`; commit** `feat(web): progressive estimate view with ranges, evidence and grounding warnings`

---

### Task 10: Chat page

**Files:**
- Create: `web/src/components/chat/{thread.tsx,composer.tsx,user-message.tsx,assistant-message.tsx,sample-picker.tsx,error-card.tsx,ai-disclosure.tsx}`, `web/src/hooks/use-thread.ts`
- Modify: `web/src/app/page.tsx`, `web/src/app/layout.tsx` (app shell, theme, `Toaster`)
- Test: `web/src/hooks/use-thread.test.ts`, `web/src/components/chat/composer.test.tsx`, `web/src/components/chat/assistant-message.test.tsx`

**Interfaces:**
- Produces: `useThread(): { turns: Turn[]; send(transcription: string): void; stop(): void; regenerate(turnId: string): void }` with `Turn = { id: string; transcription: string; state: StreamState }`, persisted to `sessionStorage` under `estimator.thread.v1` (completed turns only; capped at 20).

- [ ] **Step 1: Failing tests**
  - Composer: ⌘/Ctrl+Enter sends; Enter inserts a newline; empty input disables Send with an explanation; counter shows `n / 50,000` and turns to the warning colour above 90 %; over the limit disables Send and says "Shorten the transcript".
  - Sample picker inserts the chosen sample into the composer (does not send).
  - Assistant message: streaming shows `StatusSteps` + progressive `EstimateView` + a Stop button (Esc also stops); done shows Copy as markdown (copies `result.estimation`) and Regenerate; error shows `ErrorCard` with the mapped message and a primary action, keeping the partial content; cancelled shows "Stopped" with partial content and Regenerate.
  - `use-thread`: sending while a turn streams stops the previous one; reload restores completed turns from `sessionStorage`; corrupted storage is ignored.
- [ ] **Step 2: Implement** — layout: header (product name, environment/model chain badge from `/api/context`, theme toggle), main thread column (max width for readability), composer docked at the bottom; empty state with a one-line value statement and three sample cards; `AiDisclosure` text: "Generated by AI from your transcript. Review before sharing with a client."; a subtle note under the composer: "Each message is estimated on its own. Conversation memory arrives in a later version."
- [ ] **Step 3: `pnpm -C web test`, `make check`; commit** `feat(web): chat thread with streaming estimates, stop, regenerate and copy`

---

### Task 11: Inspector panel

**Files:**
- Create: `web/src/components/inspector/{inspector.tsx,context-tab.tsx,metrics-tab.tsx}`
- Modify: `web/src/app/page.tsx` (right panel on ≥ 1024 px, `Sheet` below)
- Test: `web/src/components/inspector/inspector.test.tsx`

- [ ] **Step 1: Failing tests** — Context tab shows the prompt version, a read-only scrollable system prompt with a Copy button, and the three references (size + meeting summary, estimation collapsed); Last call tab shows provider, model, "Fallback used" when true, prompt version, input/cached/output tokens, latency, TTFT, cost (`$0.0012`, or "n/a"), cache hit, request id with Copy; empty state "Run an estimate to see its metrics."; on < 1024 px the inspector opens from a header button as a `Sheet` and traps focus.
- [ ] **Step 2: Implement; `pnpm -C web test`, `make check`; commit** `feat(web): inspector with active prompt, CAG references and last-call metrics`

---

### Task 12: OpenAI streaming

**Files:**
- Modify: `app/services/providers/openai_provider.py`
- Create: `tests/fixtures/sse/openai/{completed,incomplete_max_tokens,refusal,failed,error_event}.txt`, `scripts/record_sse_fixture.py`
- Test: `tests/unit/providers/test_openai_stream.py`

**Interfaces:**
- Produces: `OpenAIProvider.stream(...)` per the contract; `text_format(schema: type[BaseModel]) -> dict[str, Any]` (cached; wraps `openai.lib._parsing._responses.type_to_text_format_param`).

- [ ] **Step 1: Record one real SSE body (live, ~US$0.001)** — `scripts/record_sse_fixture.py openai` streams a tiny request (short transcript, `max_output_tokens` small enough for a quick completion) through `httpx2` directly against the Responses API with the same JSON body the provider sends, saving the raw SSE text to `tests/fixtures/sse/openai/completed.txt` (strip ids you don't need; keep event order). Derive the other fixtures by editing copies: `incomplete_max_tokens` (truncate the deltas, end with `response.incomplete` and `incomplete_details.reason = "max_output_tokens"`), `refusal` (refusal content part, `status: "completed"`), `failed` (`response.failed` with `error.code = "server_error"`), `error_event` (a flat `{"type": "error", "code": "rate_limit_exceeded", ...}`). Budget-guarded.
- [ ] **Step 2: Failing tests** — serve fixtures with `httpx2.MockTransport` (status 200, `content-type: text/event-stream`) through a real `AsyncOpenAI(http_client=...)`:
  - completed → `TextDelta`s whose last `snapshot` equals the final JSON, then `LLMResult` with usage (cached tokens mapped);
  - incomplete → `InvalidModelOutput(reason="incomplete:max_output_tokens")` (never a `ValidationError`);
  - refusal → `InvalidModelOutput(reason="refusal")`;
  - failed (`server_error`) → `UpstreamUnavailable`; error event `rate_limit_exceeded` → `UpstreamRateLimited`; other codes → `UpstreamError(reason=f"stream_error:{code}")`;
  - HTTP 429 before any event → `UpstreamRateLimited`; `insufficient_quota` → `UpstreamError(reason="insufficient_quota")` (update `map_error` so quota carries that reason);
  - wire test: the request body's `text.format` equals what `responses.parse(text_format=EstimationBreakdown)` sends (capture both via MockTransport).
- [ ] **Step 3: Implement**

```python
async def stream(self, *, system: str, user: str, schema: type[T], cache_key: str) -> AsyncIterator[StreamEvent[T]]:
    start = time.perf_counter()
    terminal = None
    try:
        async with self.client.responses.stream(
            model=self.model, instructions=system, input=user, store=False,
            prompt_cache_key=cache_key, text=self._text_param(schema),
            stream_options={"include_obfuscation": False}, **self.params,
        ) as stream:
            async for event in stream:
                match event.type:
                    case "response.output_text.delta":
                        yield TextDelta(text=event.delta, snapshot=event.snapshot)
                    case "response.completed" | "response.incomplete" | "response.failed":
                        terminal = event.response
                    case "error":
                        raise stream_error(event.code)
    except openai.APIError as exc:
        raise map_error(exc) from exc
    yield self._result(terminal, schema, start)
```

`_text_param(schema)` merges `{"format": text_format(schema)}` with any `text` options already in `self.params` (e.g. verbosity) instead of passing `text` twice. `_result` handles `None` (`no_terminal_event`), `incomplete`, `failed`, refusal parts, then `schema.model_validate_json(terminal.output_text)` (`ValidationError` → `InvalidModelOutput`), and builds usage exactly like `generate()` (share a `_usage()` helper). `include_obfuscation=False` is safe here (server-to-server TLS).
- [ ] **Step 4: `make check`; commit** `feat(providers): OpenAI streaming with explicit terminal handling`

---

### Task 13: Anthropic streaming and mid-stream error mapping

**Files:**
- Modify: `app/services/providers/anthropic_provider.py`
- Create: `tests/fixtures/sse/anthropic/{completed,max_tokens,refusal,overloaded_midstream}.txt` (recorded/derived the same way as Task 12)
- Test: `tests/unit/providers/test_anthropic_stream.py`

- [ ] **Step 1: Failing tests** — completed → deltas + `LLMResult` with usage total = `input + cache_read + cache_creation`; `max_tokens` / `model_context_window_exceeded` / `refusal` → `InvalidModelOutput(reason="stop_reason:<x>")`; a mid-stream `event: error` with `overloaded_error` → `UpstreamUnavailable` (the SDK raises `APIStatusError` with `status_code == 200`); `rate_limit_error` mid-stream → `UpstreamRateLimited`; wire test: `output_config` equals `{**effort, "format": output_format(schema)}` and the system block keeps `cache_control`.
- [ ] **Step 2: Implement**

```python
STREAM_ERROR_TYPES: dict[str, type[LLMError]] = {
    "overloaded_error": UpstreamUnavailable,
    "api_error": UpstreamUnavailable,
    "rate_limit_error": UpstreamRateLimited,
}


def map_error(exc: anthropic.APIError) -> LLMError:
    if isinstance(exc, anthropic.APIConnectionError):
        return UpstreamUnavailable()
    if isinstance(exc, anthropic.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        kind = (body.get("error") or {}).get("type")
        if kind in STREAM_ERROR_TYPES:
            return STREAM_ERROR_TYPES[kind](reason=kind)
        return from_status(exc.status_code)
    return InvalidModelOutput()
```

`stream()` uses `client.messages.stream(...)` **without** `output_format` (raw `output_config` format, as `generate()` does), yields `TextDelta(event.text, event.snapshot)` for `event.type == "text"`, then `message = await stream.get_final_message()` and the same stop-reason → validation → usage path as `generate()` (extract a shared `_finish(message, schema, start)`).
- [ ] **Step 3: `make check`; commit** `feat(providers): Anthropic streaming and correct mid-stream error mapping`

---

### Task 14: Fallback router with cooldown

**Files:**
- Create: `app/services/providers/fallback.py`
- Modify: `app/config.py`, `app/services/providers/factory.py`, `app/main.py` (`/health` shows the chain), `app/services/errors.py` (if needed), `.env.example`
- Test: `tests/unit/providers/test_fallback.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass
class Cooldown:
    failures: int = 3
    seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    def available(self, key: str) -> bool: ...
    def record_failure(self, key: str) -> None: ...
    def record_success(self, key: str) -> None: ...

def falls_back(exc: LLMError) -> bool: ...   # UpstreamUnavailable | UpstreamRateLimited | reason == "insufficient_quota"

class FallbackProvider:  # implements LLMProvider; name/model = primary's
    def __init__(self, chain: Sequence[LLMProvider], cooldown: Cooldown) -> None: ...
```

Settings: `llm_fallbacks: str = "anthropic:claude-haiku-4-5"` (comma-separated `provider:model`; empty disables), `llm_cooldown_failures: int = 3`, `llm_cooldown_seconds: float = 30`; property `chain -> list[tuple[Provider, str]]`; `key_for(provider) -> str`; validation: every non-replay provider in the chain needs its key (error names the variable); unknown provider names fail at startup.

- [ ] **Step 1: Failing tests**

```python
async def test_falls_back_on_unavailable_and_reports_it() -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), name="openai")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    result = await FallbackProvider([primary, secondary], Cooldown()).generate(**ARGS)
    assert result.provider == "anthropic" and result.fallback_used and result.attempts == 2


@pytest.mark.parametrize("error", [UpstreamError(), InvalidModelOutput()])
async def test_does_not_fall_back_on_caller_or_output_errors(error) -> None:
    secondary = FakeProvider(name="anthropic")
    with pytest.raises(type(error)):
        await FallbackProvider([FakeProvider(error=error), secondary], Cooldown()).generate(**ARGS)
    assert secondary.calls == []


async def test_quota_exhaustion_falls_back() -> None:
    primary = FakeProvider(error=UpstreamError(reason="insufficient_quota"))
    result = await FallbackProvider([primary, FakeProvider(name="anthropic")], Cooldown()).generate(**ARGS)
    assert result.provider == "anthropic"


async def test_stream_falls_back_only_before_first_delta() -> None:
    early = FakeProvider(error=UpstreamUnavailable())                  # fails before yielding
    events = [e async for e in FallbackProvider([early, FakeProvider(name="anthropic")], Cooldown()).stream(**ARGS)]
    assert isinstance(events[0], ProviderSwitch) and events[0].provider == "anthropic"
    late = FakeProvider(stream_error_after_chunks=1, stream_error=UpstreamUnavailable())
    secondary = FakeProvider(name="anthropic")
    with pytest.raises(UpstreamUnavailable):
        [e async for e in FallbackProvider([late, secondary], Cooldown()).stream(**ARGS)]
    assert secondary.calls == []


async def test_cooldown_skips_a_failing_primary_then_recovers() -> None:
    clock = [0.0]
    cooldown = Cooldown(failures=2, seconds=30, clock=lambda: clock[0])
    primary = FakeProvider(error=UpstreamUnavailable())
    router = FallbackProvider([primary, FakeProvider(name="anthropic")], cooldown)
    await router.generate(**ARGS)
    await router.generate(**ARGS)
    await router.generate(**ARGS)
    assert len(primary.calls) == 2            # third call skipped the primary
    clock[0] = 31
    primary.error = None
    result = await router.generate(**ARGS)
    assert result.provider == "openai"


async def test_all_in_cooldown_still_tries_the_primary() -> None:
    cooldown = Cooldown(failures=1, seconds=30)
    a, b = FakeProvider(error=UpstreamUnavailable()), FakeProvider(error=UpstreamUnavailable(), name="anthropic")
    router = FallbackProvider([a, b], cooldown)
    with pytest.raises(UpstreamUnavailable):
        await router.generate(**ARGS)
    with pytest.raises(UpstreamUnavailable):
        await router.generate(**ARGS)
    assert len(a.calls) == 2
```

Extend `FakeProvider` with `stream_error_after_chunks` / `stream_error`. Config tests: chain parsing, missing fallback key error names `ANTHROPIC_API_KEY`, empty `LLM_FALLBACKS` = single provider, `replay` needs no key.

- [ ] **Step 2: Implement** per spec §4.2: candidates = providers not in cooldown (or `[chain[0]]` if none); `generate` and `stream` loop over candidates; in `stream`, track `started` (any `TextDelta` yielded) and re-raise once started; yield `ProviderSwitch` before trying each later candidate; on success `record_success`, return `dataclasses.replace(result, attempts=n, fallback_used=n > 1)`; failures `record_failure` and log `llm_fallback` (provider, model, cause, upstream_status, attempt) at WARNING; close each attempted stream (`aclosing`). The factory always wraps the chain (even a single provider) so logs and metrics have one shape.
- [ ] **Step 3: `make check`; commit** `feat(providers): fallback router with cooldown across providers`

---

### Task 15: Exact-match response cache (Redis, fail-open)

**Files:**
- Create: `app/services/cache.py`
- Modify: `app/config.py` (`redis_url: str | None = None`, `cache_ttl_seconds: int = 86_400`), `app/main.py` (build `RedisCache` or `NullCache` in lifespan, `aclose()` on shutdown), `app/services/llm_service.py`, `evals/run_eval.py` (always `NullCache`), `pyproject.toml` (`uv add "redis>=8.1"`, `uv add --dev "fakeredis>=2.39"`), `.env.example`
- Test: `tests/unit/test_cache.py`, `tests/unit/test_llm_service_cache.py`

**Interfaces:**
- Produces:

```python
class ResponseCache(Protocol):
    async def get(self, key: str) -> EstimateResponse | None: ...
    async def set(self, key: str, value: EstimateResponse) -> None: ...
    async def aclose(self) -> None: ...

class NullCache: ...                                     # always miss
class RedisCache:
    def __init__(self, client: redis.asyncio.Redis, *, ttl_seconds: int) -> None: ...
    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int) -> "RedisCache": ...   # socket timeouts 0.25 s, no retries

def cache_key(*, prompt_version: str, system: str, user: str, scope: str, schema_name: str) -> str: ...  # "estimate:<sha256>"
def cache_scope(settings: Settings) -> str: ...          # canonical JSON of chain + temperature + effort + max output tokens
```

`EstimationService.__init__` gains `cache: ResponseCache` and `cache_scope: str`.

- [ ] **Step 1: Failing tests**

```python
async def test_round_trip_with_ttl() -> None:
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    cache = RedisCache(client, ttl_seconds=60)
    await cache.set("estimate:abc", response_fixture())
    assert await cache.get("estimate:abc") == response_fixture()
    assert 0 < await client.ttl("estimate:abc") <= 60


async def test_outage_is_a_miss_not_an_error(caplog) -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    cache = RedisCache(fakeredis.FakeAsyncRedis(server=server, decode_responses=True), ttl_seconds=60)
    assert await cache.get("estimate:x") is None
    await cache.set("estimate:x", response_fixture())      # no exception
    assert "cache_error" in caplog.text


async def test_stale_or_corrupt_entry_is_a_miss() -> None:
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    await client.set("estimate:x", '{"not": "a response"}')
    assert await RedisCache(client, ttl_seconds=60).get("estimate:x") is None


def test_key_changes_with_every_input() -> None:
    base = dict(prompt_version="v4", system="S", user="U", scope="openai:gpt-4o-mini|t=0.2", schema_name="EstimationBreakdown")
    keys = {cache_key(**base)} | {cache_key(**(base | {k: base[k] + "x"})) for k in base}
    assert len(keys) == 1 + len(base)
    assert cache_key(**base).startswith("estimate:")
```

```python
# tests/unit/test_llm_service_cache.py
async def test_second_identical_request_is_served_from_cache(service_with_fakeredis, fake) -> None:
    first = await service_with_fakeredis.estimate(request())
    second = await service_with_fakeredis.estimate(request())
    assert len(fake.calls) == 1
    assert first.metrics.cache_hit is False and second.metrics.cache_hit is True
    assert second.metrics.cost_usd == 0 and second.metrics.attempts == 0


async def test_stream_cache_hit_emits_status_then_result(service_with_fakeredis) -> None:
    await service_with_fakeredis.estimate(request())
    items = [i async for i in service_with_fakeredis.estimate_stream(request())]
    assert [type(i).__name__ for i in items] == ["StatusEvent", "EstimateResponse"]
    assert items[0].phase == "cache_hit"


async def test_failures_and_cancellations_are_not_cached(service_with_fakeredis_failing, client) -> None:
    with pytest.raises(UpstreamUnavailable):
        await service_with_fakeredis_failing.estimate(request())
    assert await client.keys("estimate:*") == []
```

- [ ] **Step 2: Implement** — fail-open on `redis.exceptions.RedisError` only (log `cache_error` with the exception class, never the key contents); narrow `get()` results with `isinstance(v, str)`; invalid JSON or `ValidationError` → `cache_stale` log + miss. In the service: compute the key from the actual system/user strings sent; on hit return the cached response with `metrics` replaced (`cache_hit=True`, `cost_usd=0`, `attempts=0`, `latency_ms` = lookup time); on miss call the provider, then `set` before returning/yielding the result; in the stream path wrap the `set` in `with anyio.CancelScope(shield=True), anyio.move_on_after(0.5):` so a disconnect cannot leave a half-finished write blocking. `llm_call` logs gain `cache=hit|miss|error|bypass`; a hit logs `estimate_cache_hit` (no `llm_call`, since no LLM call happened).
- [ ] **Step 3: `make check`; commit** `feat(cache): exact-match Redis response cache, fail-open`

---

### Task 16: Cassette recorder and live smoke test

**Files:**
- Create: `scripts/record_cassettes.py`, `scripts/smoke_live.py`, `tests/cassettes/*.json` (recorded)
- Modify: `Makefile` (`record-cassettes`, `smoke-live`)
- Test: `tests/unit/test_smoke_live.py` (pure helpers only)

- [ ] **Step 1: Recorder** — for each file in `web/src/content/samples/`, build the exact system/user strings the service sends, call `OpenAIProvider.stream(...)` with real settings, record `[elapsed_ms, text]` per delta and the final usage, write `tests/cassettes/<cassette_key>.json`; `ensure_budget(0.01)` before, `record_spend("record-cassettes", cost)` after (cost from `pricing.cost_usd`).
- [ ] **Step 2: Smoke** — three checks, each printed as one table row (`check | provider served | fallback | ttft ms | latency ms | cost usd | result`): (1) stream via OpenAI `gpt-4o-mini`; (2) stream via Anthropic `claude-haiku-4-5`; (3) forced fallback: primary OpenAI client with `base_url="http://127.0.0.1:9"` and a 2 s timeout, fallback Anthropic → must report `fallback_used=True` and provider `anthropic`. Exit 1 if any check fails. Budget: `ensure_budget(0.05)`; record actual spend.
- [ ] **Step 3: Unit-test the pure helpers** (table formatting, cassette key reuse). `make check`; commit `chore(live): cassette recorder and live smoke test with spend guard`.
- [ ] **Step 4: Run them live** — `make record-cassettes && make smoke-live`; paste the smoke table in the transcript; commit the cassettes `test(fixtures): recorded cassettes for the sample transcripts`.

---

### Task 17: Docker and Compose

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `web/Dockerfile`, `web/.dockerignore`, `compose.yaml`, `compose.dev.yaml`, `compose.e2e.yaml`
- Modify: `Makefile` (`up`, `dev`, `down`, `logs`), `.env.example` (`REDIS_URL`, `CACHE_TTL_SECONDS`, `LLM_FALLBACKS`, `LLM_COOLDOWN_*`, `REPLAY_*`, `LIVE_BUDGET_USD`), `README.md` (run section)

**Interfaces:**
- Produces: `make up` → `docker compose up --build --wait` (web on http://localhost:3000 only); `make dev` → `docker compose -f compose.yaml -f compose.dev.yaml up --build --watch`; `make down`; `compose.e2e.yaml` overrides `ai-service` with `LLM_PROVIDER=replay`, `LLM_FALLBACKS=` and mounts `./tests/cassettes:/app/tests/cassettes:ro`.

- [ ] **Step 1: AI service image** — uv multi-stage per `.claude/stack.md` "Docker": builder copies uv from `ghcr.io/astral-sh/uv:<pinned>`, `uv sync --locked --no-install-project --no-dev` with cache mounts, then the project; `runtime` = `python:3.12-slim`, non-root user, only `.venv` + `app/`, `HEALTHCHECK` on `/health` (python one-liner, no curl), `CMD uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --timeout-graceful-shutdown 30`; `dev` target adds `--reload`.
- [ ] **Step 2: Web image** — Next.js standalone multi-stage with pnpm per `.claude/stack.md`; non-root; `HEALTHCHECK` hitting `/` via node fetch; `AI_SERVICE_URL` read at runtime (server-only), never baked into the client bundle.
- [ ] **Step 3: Compose** — services `web` (ports `3000:3000`, `AI_SERVICE_URL=http://ai-service:8000`, depends on ai-service healthy), `ai-service` (no `ports:`, `env_file: .env`, `REDIS_URL=redis://redis:6379/0` override, depends on redis healthy), `redis` (`redis:8-alpine`, no ports, `--save "" --appendonly no`, healthcheck `redis-cli ping`). `compose.dev.yaml`: ai-service `target: dev`, ports `8000:8000`, `develop.watch` (`sync` `./app` → `/app/app`, `rebuild` on `uv.lock`/`pyproject.toml`); web runs `pnpm dev` with `sync` of `web/src` and `rebuild` on `web/pnpm-lock.yaml`. Do not bind-mount the same paths you sync (watch ignores them).
- [ ] **Step 4: Verify** — `make up` (paste the `--wait` output), `curl -s localhost:3000/api/context | head -c 200`, confirm `curl -s localhost:8000/health` fails (internal only), `make down`. Commit `build: Docker images and Compose for web, ai-service and redis`.

---

### Task 18: End-to-end tests, accessibility and media

**Files:**
- Create: `web/playwright.config.ts`, `web/e2e/chat.spec.ts`, `docs/media/session-03/*`
- Modify: `Makefile` (`e2e`: `docker compose -f compose.yaml -f compose.e2e.yaml up --build --wait && pnpm -C web exec playwright test; status=$?; docker compose -f compose.yaml -f compose.e2e.yaml down; exit $status`)

- [ ] **Step 1: Specs** (replay provider, zero spend):
  - load → empty state with three samples; pick "Clinic portal" → Send → status steps visible → at least one partial render (project name appears before the totals strip leaves its skeleton) → result with totals, tasks table, evidence hover card → Copy puts markdown on the clipboard → inspector "Last call" shows provider `replay`, a request id;
  - Stop mid-stream → "Stopped" state with partial content, Regenerate works;
  - reload → completed turn restored;
  - keyboard only: Tab to composer, ⌘/Ctrl+Enter sends, Esc stops;
  - `@axe-core/playwright` on empty, streaming and result states: zero `serious`/`critical` violations, in light and dark themes;
  - viewport 375 px: inspector opens as a sheet, no horizontal scroll.
- [ ] **Step 2: Media** — screenshots (empty state, streaming, result with inspector, dark theme, mobile) and a GIF (Playwright video → `ffmpeg` if available, else keep the `.webm`) into `docs/media/session-03/`.
- [ ] **Step 3: `make e2e`; commit** `test(e2e): chat streaming, stop, keyboard and accessibility`

---

### Task 19: CI

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1** — keep one workflow and one job if it stays under ~6 minutes: add `pnpm/action-setup` (pinned SHA, version from `web/package.json` `packageManager`), `actions/setup-node` with pnpm cache, `pnpm -C web install --frozen-lockfile`, keep `make check` (now includes web), add `docker compose build` (catches broken Dockerfiles). Pin every action by full SHA with a version comment. No e2e in CI (needs Docker + time; it runs in `make gate`).
- [ ] **Step 2** — push the branch and confirm CI passes: `gh run watch` (use `GH_TOKEN=$(gh auth token --user ethx42)`); paste the conclusion. Commit `ci: web checks and image builds`.

---

### Task 20: Branch close-out

**Files:** `README.md`, `openspec/specs/{estimation-api,llm-providers,configuration,quality-gates}/spec.md` (+ new `openspec/specs/response-cache/spec.md` if cleaner), `docs/takeaways/session-03.md`, `docs/catch-up/PROGRESS.md`, `.claude/stack.md` (anything new learned)

- [ ] **Step 1: README** — architecture diagram updated (web → BFF → ai-service → providers/redis); how to run (`make up`, `make dev`, `make check`, `make e2e`, `make smoke-live`); "Session 3" section mapping the brief checklist (React instead of Streamlit, allowed by the session 4 brief): chat opens in the browser; paste transcript → estimate; conversation persists on screen (sessionStorage); streaming token by token; API keys only in the AI service env (never in the browser or the code); level 3 inspector; plus the live-class layer (fallback, cache, cost, logs); the smoke table; media links.
- [ ] **Step 2: Specs (OpenSpec-lite)** — add/modify requirements and scenarios for: streaming endpoint and SSE protocol, context endpoint, call metrics, fallback router and cooldown, response cache, replay provider, new configuration variables, web checks in the quality gate. `make specs` green.
- [ ] **Step 3: Review panel and fixes** — per `HANDOFF.md` (Workflow tool, ≤ 8 agents: AI correctness; streaming/cancellation/concurrency; security incl. BFF forwarding, secrets, SSRF, logs; UI/accessibility/visual hierarchy via `gsd-ui-review` + screenshots). Each confirmed finding: failing test → fix → commit.
- [ ] **Step 4: Takeaways** — `docs/takeaways/session-03.md` covering spec §5.4 topics, each with concept, why it exists, trade-offs, alternatives with greater benefit and when to switch, evidence from this branch (smoke table, TTFT numbers, cache hit timings); 6–8 quiz questions with answers in `<details>`; `humanizer` pass.
- [ ] **Step 5: Gate and push** — update `PROGRESS.md`; `git push -u origin pre-session-03`; `make gate BRANCH=pre-session-03` (must print `GATE PASS pre-session-03 <sha>`); `git log -1 --oneline origin/pre-session-03`; `cat docs/catch-up/PROGRESS.md`; PushNotification "pre-session-03 pushed: <one-line result>".
