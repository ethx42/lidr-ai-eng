# Catch-up spec: sessions 3–5

Status: approved in conversation on 2026-10-06; the written-spec review was explicitly waived by the owner (implementation starts from this file).
Branches: `pre-session-03` → `pre-session-04` → `pre-session-05`, each cut from the previous one; `pre-session-03` is cut from `main` (tag `m1`).

## 1. Intent

The owner fell behind on the course briefs for sessions 3, 4 and 5 (deadlines 2026-09-21, 09-28, 10-05; the session 5 live class is on 2026-10-07). M1 (the session 2 brief) shipped, but it was over-engineered and the owner did not learn the course concepts. This catch-up delivers one branch per session that:

- satisfies that session's brief verification checklist (briefs: `~/Downloads/Sesion {3,4,5} ✍️ Ejercicio - … .pdf`; reference solutions: `https://github.com/LIDR-academy/ai-engineering`, branches `session_3`, `session_4`, `session_5`);
- also delivers the live-class content that the next brief assumes (session 3 live: provider wrapper with fallback, exact-match cache, streaming, logging; session 4 live: structured output and output guardrails, which M1 already has);
- treats the **AI service as the product core, built to a top-tier standard**, and adds a production-grade web client;
- carries deep key takeaways with alternatives that could bring greater benefits, plus a self-check quiz, because the owner learns by reviewing and being quizzed (the owner chose: "Claude implements, owner reviews, Claude quizzes").

Constraints stated by the owner: everything in English (code, docs, prompts, commits); one branch per session; React-based client; enterprise-level UI with strong usability and visual hierarchy, no decorative animation; Docker so the system is self-contained; moderate live LLM spend (keys auto top-up, so the budget guard is ours); push branches when done; no PRs; the owner emails the branch links.

Success: each branch passes its brief checklist and the gates in §9, and the owner can defend the session's learning objectives (session 4 lists them explicitly) after reading the takeaways.

## 2. Architecture

```
Browser ──► web/ (Next.js App Router: React UI + route handlers = BFF)  ──► AI service (FastAPI, repo root)
            only public service (port 3000)                                internal only (ai-service:8000)
                                                                           ├─ providers: OpenAI | Anthropic | replay, behind a fallback router
                                                                           ├─ prompts: Jinja2, versioned (from session 4)
                                                                           ├─ cache: Redis exact-match (fail-open)
                                                                           └─ sessions: in-process store (session 5)
                                                                      redis (internal)
```

The course's final architecture (`main` of the reference repo) is the same split: `ai-service/` (FastAPI, all AI logic) and `business-backend/` (Rails as UI and business backend). The briefs allow any client and business-backend stack; the AI service is always Python + FastAPI.

Repository layout after the catch-up (new items only):

```
compose.yaml, compose.dev.yaml       # whole system; dev override adds ports, reload, watch
Dockerfile                           # AI service (targets: dev, runtime)
contracts/openapi.json               # committed OpenAPI snapshot of the AI service (contract source of truth)
web/                                 # Next.js app (own Dockerfile, package.json, tests)
docs/catch-up/{spec,plan-session-0N,PROGRESS,HANDOFF}.md, spend.jsonl
docs/takeaways/session-0N.md         # one per branch
docs/media/session-0N/               # screenshots and GIF produced by Playwright
app/prompts/estimation/vN/*.j2       # from session 4
app/sessions.py, app/attachments/    # from session 5
```

The Python service stays at the repository root (moving it to `ai-service/` would be churn without value now).

## 3. Decisions

Each decision lists what was rejected. These are the "alternatives" seeds for the takeaways.

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | **Next.js App Router + TypeScript as UI and BFF** (`web/`). | Same role as the course's Rails app, in React. Keeps the AI service private from day one, keys and future auth live server-side. Grows into auth (Auth.js/Better Auth) and Postgres (Drizzle) without a rewrite. | Vite SPA calling FastAPI directly (exposes the AI service, business layer rebuilt later); SPA + separate business API (three services for one client); Streamlit (internal-tool only). |
| D2 | **Structured streaming via server-side partial snapshots.** The provider streams JSON deltas; the AI service accumulates them, parses with `jiter` partial mode, and emits SSE `partial` events, then one validated `result`. | Keeps M1's guarantees (schema validation, grounding, totals in code) while the user watches the estimate build. One code path for both providers; clients stay simple. | Free-text streaming like the course (loses structure, and session 5 requires structured output); passing raw JSON tokens to clients (every client re-implements partial parsing on unvalidated output). |
| D3 | **Own thin router over native SDKs** (`FallbackProvider`, composition over the existing provider protocol). | Native features stay available (Responses structured output, Anthropic `cache_control`, per-model effort profiles, streaming snapshots). ~60 lines on top of what M1 has. | LiteLLM Router (lowest-common-denominator API; the course's own config load-balanced instead of falling back and they bypassed it for streaming; PyPI supply-chain compromise of 1.82.7/1.82.8 on 2026-03-24 that stole `.env` files and cloud credentials); an external gateway (Portkey, LiteLLM Proxy, Cloudflare or Vercel AI Gateway: right when several apps or teams need central keys, budgets and audit). |
| D4 | **Exact-match response cache in Redis, fail-open**, behind a `ResponseCache` protocol (`RedisCache`, `NullCache`). | Multi-worker safe, survives restarts, matches the course. A Redis outage degrades to "no cache", never to an error. | In-process dict (wrong with more than one worker); semantic cache (session 4 live content, out of scope). |
| D5 | **Docker Compose for the whole system**; only `web` publishes a port. `compose.dev.yaml` adds published ports, reload and `develop.watch`. | Self-contained, mirrors production posture (the course only hides the AI service in session 15). API keys reach only the AI service through `env_file`, so a key exported in the host shell does not leak in. | Local processes only (no isolation, "works on my machine"). |
| D6 | **Contract-first.** `contracts/openapi.json` is generated from FastAPI and committed; `web/` generates TypeScript types from it (`openapi-typescript` + `openapi-fetch`). `make check` fails when the snapshot is stale. SSE event payloads are Pydantic models included in the OpenAPI components. | Schema drift breaks the build, not production. Lets the AI and web tracks run in parallel. | Hand-written TS types (drift). |
| D7 | **`replay` provider.** Streams a recorded cassette (real provider deltas with timing) when one matches the request, otherwise synthesises a stream from a fixture breakdown. | Deterministic e2e tests, offline web development, demos with zero spend. | Per-test mocks only (no realistic streaming in the browser). |
| D8 | **Keep `transcription` and structured output in session 4**; add the brief's enums. | Session 5's starting point requires structured output and a transcription; the brief's 2000-char `description` cannot hold a meeting transcript (the course's own solution raised it to 80k). | Brief-literal `description` + free-text `{text, prompt_version}` (a regression that session 5 would undo). |
| D9 | **Jinja prompts restart numbering under the use-case namespace**: `app/prompts/estimation/v1` is a faithful port of M1 `v4`; `v2` is a deliberate change (§6.4). M1's `app/prompts/v1..v4` are removed; their history stays in git and in `evals/reports/`. | Brief mandates the path and `v1`; a faithful port makes the eval comparison meaningful. | Naming the port `v5` (breaks the brief's paths and tests). |
| D10 | **Session 5:** attachments via local extraction (path B: `pypdf` + `python-docx`); `project_metadata` derived from the structured output (no extra LLM call); history stores the assistant turn as compact markdown, windowed by turns **and** by size. | Provider-agnostic, grounding can check quotes against attachment text, prepares RAG chunking; no added latency or cost per turn; bounded tokens. | Path A Files API (better for diagrams and images; provider-coupled); PyMuPDF (AGPL, a problem for a closed commercial product); regex heuristic (brittle); separate LLM extractor (+1 call per turn). |
| D11 | **OpenSpec-lite.** No `openspec/changes/` folders for these branches; at the end of each branch the affected `openspec/specs/*/spec.md` are updated in place so they stay true; `make specs` stays green. | The owner asked for less process; specs still must not lie. | Full propose/apply/verify/archive per branch (the overhead that slowed M1). Recorded here as the comply-or-explain deviation from `AGENTS.md`. |
| D12 | **Live-spend guard.** Every live command (smoke, eval, cassette recording) reads `LIVE_BUDGET_USD` (default 5) and the running total in the append-only ledger `docs/catch-up/spend.jsonl`, and refuses to run past it; `PROGRESS.md` shows the total. Only `gpt-4o-mini` and `claude-haiku-4-5` are used live. | Provider auto top-up means no external cap. | Trusting provider limits. |

## 4. AI service contract (shared by all branches)

### 4.1 Provider protocol

`LLMProvider` (in `app/services/providers/base.py`) gains a streaming method; results carry who served them:

```python
@dataclass(frozen=True)
class LLMResult[M: BaseModel]:
    parsed: M
    usage: Usage
    latency_ms: int
    provider: Provider          # "openai" | "anthropic" | "replay"
    model: str

@dataclass(frozen=True)
class TextDelta:
    text: str

StreamEvent = TextDelta | LLMResult  # exactly one LLMResult, last

class LLMProvider(Protocol):
    name: Provider
    model: str
    async def generate(self, *, system: str, user: str, schema: type[T], cache_key: str) -> LLMResult[T]: ...
    def stream(self, *, system: str, user: str, schema: type[T], cache_key: str) -> AsyncGenerator[StreamEvent]: ...  # a generator, so callers can aclose() it
    async def aclose(self) -> None: ...
```

From session 5, `user: str` becomes `messages: Sequence[ChatMessage]` (a one-message list for single-turn calls).

Provider implementations use the SDKs' native streaming with the JSON schema sent raw and the final text validated in code; the SDKs' parsing stream helpers (`text_format=` / `output_format=`) are not used because they raise mid-stream before the stop condition is readable (see `.claude/stack.md`). Error mapping and stop-condition handling (incomplete, truncation, refusal → `InvalidModelOutput` with a reason) match the blocking path. Closing the async iterator closes the upstream stream.

### 4.2 Fallback router

`FallbackProvider(chain: Sequence[LLMProvider], cooldown: Cooldown)` implements `LLMProvider`.

- Chain from settings: primary = `LLM_PROVIDER`/`LLM_MODEL`; `LLM_FALLBACKS` = comma-separated `provider:model` (default `anthropic:claude-haiku-4-5`; `none` disables fallback — an empty environment value is ignored by pydantic-settings and keeps the default). Startup fails if any provider in the chain lacks its key (except `replay`).
- Falls back on `UpstreamUnavailable`, `UpstreamRateLimited` and quota-exhausted `UpstreamError`; never on other 4xx `UpstreamError` or `InvalidModelOutput`.
- Streaming: falls back only before the first `TextDelta` has been yielded; after that the error propagates.
- Cooldown: after `LLM_COOLDOWN_FAILURES` (3) consecutive availability failures a provider is skipped for `LLM_COOLDOWN_SECONDS` (30); a success resets the count. In-process state.
- Every attempt is logged (§4.6).

### 4.3 Response additions

`EstimateResponse` gains `metrics: CallMetrics`:

```python
class CallMetrics(BaseModel):
    latency_ms: int
    ttft_ms: int | None          # streaming only: time to first delta
    cost_usd: float | None       # None when the model has no price entry
    cache_hit: bool
    fallback_used: bool
    attempts: int
```

`provider` and `model` report the provider that actually served the result. Prices live in `app/services/pricing.py` (per 1M tokens: input, cached input, output; with an `as_of` date and source URL).

### 4.4 Streaming endpoint and SSE protocol

`POST /api/v1/estimate/stream` takes the same body as `POST /api/v1/estimate` and returns `text/event-stream` via FastAPI's native `EventSourceResponse`. Validation errors (422) are returned as normal JSON before the stream starts.

| Event | Data (Pydantic model) | Rules |
|---|---|---|
| `status` | `{phase: "calling_llm" \| "fallback" \| "validating" \| "cache_hit", provider?, model?}` | Informational, any number. |
| `partial` | `{seq: int, breakdown: dict}` (partial `EstimationBreakdown`, possibly incomplete) | Only after the first delta; emitted when the parsed snapshot changed, at most every 100 ms plus one unthrottled final flush before the terminal event; `seq` strictly increasing. |
| `result` | `EstimateResponse` | Terminal. |
| `error` | `{code, message, retryable: bool, request_id}` | Terminal. Codes match the HTTP error taxonomy. |

Exactly one terminal event per stream. Keep-alive comments every 15 s. Headers disable proxy buffering. A cache hit emits `status{cache_hit}` then `result`. A client disconnect closes the upstream stream promptly, logs `outcome=cancelled`, and caches nothing.

### 4.5 Exact-match cache

- Key: SHA-256 over canonical JSON of `{cache_schema: 2, prompt_version, prompt_sha256 (rendered system + user), chain: ["provider:model", …], params (temperature, effort, max output tokens, blended hourly rate, weekly capacity hours — both are baked into the cached totals), output schema name}`; stored as `estimate:{hex}`. `cache_schema` is bumped whenever what an entry stores changes (session 4's markdown layouts took it from 1 to 2).
- Value: the `EstimateResponse` JSON. On a hit, `metrics.cache_hit = true`, `cost_usd = 0`, `attempts = 0`.
- TTL `CACHE_TTL_SECONDS` (86400). `REDIS_URL` unset → `NullCache`.
- Any Redis error logs `cache_error` and is treated as a miss (get) or ignored (set). Only successful results are stored.
- Session 5 conversational endpoints bypass the cache (history-dependent).

### 4.6 Observability

The existing one-record-per-LLM-call rule stays (`llm_call`, no transcript or keys in any log). New fields: `attempt`, `fallback` (bool), `stream` (bool), `ttft_ms`, `cost_usd`, `cache` (`hit|miss|error|bypass`), `outcome` adds `cancelled`. From session 4: a `prompt_rendered` record with version and SHA-256 of the rendered prompt (never the content).

### 4.7 Context endpoint

`GET /api/v1/context` returns `{prompt_version, system_prompt, references: [...], chain: ["provider:model", …], max_transcription_chars}` for the UI inspector. From session 4 it accepts the same enum query parameters as the estimate request (the system prompt depends on them) and `prompt_version`, and also returns `available_versions`; when `prompt_version` is omitted the default is `PROMPT_VERSION` (settings).

## 5. Branch `pre-session-03`: conversational interface with streaming

Brief: React chat that sends a transcript, keeps the conversation visible, streams the answer token by token, never hardcodes keys; level 3 (optional, in scope): sidebar with the active system prompt, the injected CAG context, and last-call metrics. The brief's Streamlit file is replaced by `web/`, which the session 4 brief explicitly allows; the README maps each checklist item to the web equivalent.

### 5.1 AI service

1. Provider streaming for OpenAI and Anthropic (§4.1) with recorded-fixture unit tests (mock transport SSE bodies): deltas, final parse, incomplete/truncated, refusal, mid-stream error mapping, close-on-cancel.
2. `PartialSnapshotter`: takes the accumulated text (the caller accumulates deltas), `jiter` partial parse, change detection, 100 ms throttle; never raises on malformed partials.
3. `FallbackProvider` + cooldown (§4.2); settings refactor (`key_for(provider)`; chain validation).
4. `pricing.py` + `CallMetrics` (§4.3).
5. `ResponseCache` (§4.5) with `RedisCache` (`redis.asyncio`) and `NullCache`; tests with `fakeredis`.
6. `replay` provider (D7; `LLM_PROVIDER=replay` needs no key of its own; with the default chain it still needs the fallback's key, so offline runs set `LLM_FALLBACKS=none`) + `make record-cassettes` (live, budget-guarded) for the sample transcripts used by the UI; cassettes in `tests/cassettes/` keyed by the SHA-256 of the rendered prompt pair.
7. `EstimationService.estimate_stream()` sharing enrichment, grounding and rendering with `estimate()`; `/api/v1/estimate/stream` (§4.4); `/api/v1/context` (§4.7).
8. `contracts/openapi.json` + `make openapi` / snapshot check in `make check`.
9. Logging fields (§4.6).

### 5.2 Web (`web/`)

- Scaffold: Next.js (latest stable), TypeScript strict, Tailwind v4, shadcn/ui, pnpm; lint, typecheck, Vitest + Testing Library; Playwright + axe.
- BFF route handlers: `POST /api/estimate/stream` (pipes the upstream SSE body, propagates abort to upstream), `GET /api/context`. `AI_SERVICE_URL` is server-only.
- Typed client generated from `contracts/openapi.json`; SSE parsing with `eventsource-parser` in a `useEstimateStream` hook (states: idle → streaming → done | error | cancelled).
- Screens and patterns (§8): chat thread kept in the session (React state + `sessionStorage`); composer with paste, sample transcripts, character counter against the limit, ⌘↵ / Esc; assistant message renders the estimate progressively from `partial` snapshots with skeletons shaped like the final layout; Stop, Regenerate, Copy as markdown; status steps; actionable error card that keeps partial content; AI disclosure label; inspector panel (system prompt, references, last-call metrics incl. provider, fallback, prompt version, tokens incl. cached, latency, TTFT, cost, cache hit, request id). Each turn is estimated independently; the UI says so (memory arrives in session 5).

### 5.3 Infra

`Dockerfile` (AI service: uv multi-stage, `dev` + `runtime`, non-root, healthcheck, one worker), `web/Dockerfile` (standalone output, non-root), `compose.yaml` (`web`, `ai-service`, `redis`; healthchecks; `depends_on: service_healthy`), `compose.dev.yaml`; Makefile targets `up`, `dev`, `down`, `openapi`, `web-check`, `e2e`, `smoke-live`, `record-cassettes`; CI adds the web checks and `docker compose build` while staying a single concise workflow.

### 5.4 Takeaways topics (`docs/takeaways/session-03.md`)

SSE vs WebSocket vs chunked HTTP, SSE over POST and why not `EventSource`; streaming structured output and partial parsing; TTFT and perceived latency; cancellation propagation and its cost impact; the three cache layers (provider prompt cache vs app exact-match vs semantic) and cache-key design; fail-open; fallback triggers, idempotency, cooldowns; router vs gateway (with the LiteLLM incident); BFF and keeping the AI service private; history is not memory. Alternatives with greater benefit: resumable streams (`Last-Event-ID` + Redis Streams), Vercel AI SDK `useObject`-style UIs, gateways, semantic cache.

## 6. Branch `pre-session-04`: from chat to product interface

Brief deliverable branch name: `pre-session-04`. Learning objectives to defend: typed form vs free textarea; `.j2` + loader vs f-string; prompt versioning and why `v1/`, `v2/` is not optional; what a template test covers and what it does not.

### 6.1 Contract

- Enums exactly as the brief: `ProjectType {mobile_app, web_saas, internal_tool, data_pipeline}`, `DetailLevel {summary, medium, detailed}`, `OutputFormat {phases_table, line_items, narrative}`.
- `EstimateRequest = transcription + project_type + detail_level + output_format (+ output_language)`; the three enums are required (the brief's typed form). Golden eval cases declare them in front matter.
- Schemas stay in `app/schemas/estimation.py` (the brief's `app/schemas.py` cannot coexist with the existing `app/schemas/` package; README maps it).
- Response unchanged in shape (structured + `prompt_version` + `metrics`).

### 6.2 Prompts (brief-mandated paths)

- `app/prompts/loader.py` exposes `render_estimation_prompt(request, version="v1") -> tuple[str, str]` with `Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, autoescape=False)`.
- `app/prompts/estimation/v1/{system,user,examples}.j2`. `system.j2` includes `examples.j2`, which loops over the typed references from `app/context/examples.py` (single source of truth stays typed and tested).
- **Block order for prompt caching:** static content first (role, rules, references), enum-dependent blocks (`output_format`, `detail_level`) last. A test asserts that two different enum combinations share the same long prefix.
- `detail_level` and `output_format` change the instructions (as the brief's tests require). `output_format` also picks the markdown layout rendered in code (`phases_table` = phase rollup table, `line_items` = task table, `narrative` = prose per phase); `detail_level` drives the instructions only (the brief asks for no per-detail layout).
- Transcript delimiter neutralisation is kept (prompt-injection defence).
- Endpoints accept `?prompt_version=v1|v2` (422 for unknown versions; omitted → `PROMPT_VERSION` setting); `prompt_rendered` log (§4.6).

### 6.3 Tests

`tests/prompts/test_estimation_v1.py` (brief path): transcript lands inside its delimiter block; `phases_table` keyword present for `phases_table` and absent for `narrative`; `detailed` adds the per-phase assumptions instruction and `summary` does not; plus `StrictUndefined` failure, version switch, delimiter neutralisation, shared static prefix. All offline, milliseconds.

### 6.4 Prompt `v2` and the eval gate

- `v1` (faithful port) must score ≥ `evals/baseline.json` − 0.02 on `gpt-4o-mini`; the baseline is then re-recorded (after the `covers_frontend` check is added) from the winning version.
- `v2` is a deliberate change that fixes the M1 carry-over "estimates skip frontend tasks for client-facing surfaces": an explicit coverage rule, plus a new eval check (frontend task present when the transcript mentions a client-facing surface). The v1 vs v2 comparison goes in the README eval table and the takeaways.

### 6.5 Web

The chat becomes a typed form: transcript (paste, sample, `.txt` upload), segmented controls for the three enums, advanced disclosure with prompt version, one primary "Estimate" action, inline validation. Results in a resizable split view: transcript on the left with evidence highlights, estimate on the right; hovering or focusing a requirement highlights and scrolls to its quote (keyboard accessible). Streaming, inspector and error patterns from session 3 carry over.

### 6.6 Takeaways topics

The four brief objectives in depth; prompt-cache-aware template ordering; template tests vs evals; prompt registries (Langfuse, PromptLayer) and when to adopt one; Jinja `SandboxedEnvironment` and when templates come from untrusted authors; typed forms vs chat vs hybrid "form + refine" UIs.

## 7. Branch `pre-session-05`: conversational memory and enriched context

Brief deliverable branch name: `pre-session-05`. Paths `/sessions` and `/sessions/{session_id}/estimate` are brief-mandated (no `/api/v1` prefix).

### 7.1 AI service

- `app/sessions.py` (brief path): `ConversationHistory` (sliding window, `MAX_TURNS` default 6, a turn = user + assistant pair, oldest pairs dropped first, also dropped while the history exceeds `MAX_HISTORY_CHARS` (default 60000); system prompt is not stored and is regenerated each turn; `to_messages_list(system)`), `ProjectMetadata` (`project_name`, `assumed_team_size`, `mentioned_technologies`, `agreed_scope`), `Session`, `SessionStore` protocol with `InMemorySessionStore` (max sessions + idle TTL; docstrings explain why volatility is acceptable now and what replaces it: Redis or Postgres).
- `POST /sessions` → `201 {"session_id": uuid4}`. `GET /sessions/{id}` → metadata + turn count (for the UI panel). `POST /sessions/{id}/estimate` (multipart: `transcript`, the three enum fields, `attachments: list[UploadFile] | None`) → `EstimateResponse` plus `project_metadata` and `history_turns`; `/sessions/{id}/estimate/stream` is the SSE variant with the same events. Unknown session → 404.
- Attachments (`app/attachments/`): PDF (`pypdf`), DOCX (`python-docx`), plain text; type detected by magic bytes, not by extension; limits (settings, defaults): 5 files, 10 MB per file, 200 pages in total, 50000 extracted characters in total; encrypted or unreadable files → 422 with a clear message; extraction runs off the event loop. Extracted text is appended as `--- attachment: <filename> ---` blocks inside the transcript delimiter and neutralised like the transcript. Grounding checks evidence against transcript + attachments.
- Prompt `estimation/v3`: adds a `<project_metadata>` block at the end of the system prompt (empty on the first turn).
- Schema adds `technologies: list[str]` to the LLM output. Metadata merge in code after each turn: `project_name` = latest non-empty; `assumed_team_size` = sum of team counts; `mentioned_technologies` = case-insensitive union, capped; `agreed_scope` = latest summary.
- Providers accept `messages` (§4.1); system prompt keeps its cacheable prefix.
- README states the attachment path and the metadata strategy with their rationale (brief requirement).

### 7.2 Tests (brief §7, with `httpx2.AsyncClient` + ASGI transport and lifespan)

1. A session linking two requests updates `project_metadata`.
2. A PDF attachment changes the estimate (fake provider derives a field from attachment text; fixtures: a tiny PDF and DOCX committed with their generation script).
3. Eight turns to one session: the history sent to the provider never exceeds `MAX_TURNS` pairs.
Plus unit tests for the window, the size cap, the merge rules, extraction limits and magic-byte detection.

### 7.3 Web

Session created on load through the BFF (`session_id` in React state + `sessionStorage`); "New conversation" creates a new one; composer = session 4 form + multi-file dropzone (type and size checked client-side, chips with per-file status, removable); BFF forwards multipart to the AI service; thread of turns with the estimate view and a "what changed" totals delta vs the previous turn; "Project memory" panel showing metadata with this-turn changes highlighted; context meter "history N / 6 turns" with an explanation.

### 7.4 Takeaways topics

History vs memory; sliding window failure modes (lost anchors, forgotten decisions) and what the live class adds (cumulative summary, anchors, dynamic tier); separating facts from history; path A vs path B decision matrix; multipart with typed params in FastAPI; process-local state with multiple workers and restarts; prompt injection through documents; alternatives with greater benefit (Redis or Postgres sessions, memory services such as mem0 or Zep, Files API for diagrams).

## 8. UX and visual standard (all branches)

- References: Microsoft HAX Guidelines for Human-AI Interaction, Google PAIR People + AI Guidebook, Nielsen's heuristics, Shape of AI patterns, WCAG 2.2 AA.
- Patterns: visible system status (skeletons shaped like the result, status steps, no spinners); user control (Stop cancels server-side, Regenerate, Copy, keyboard shortcuts); explain why (evidence quotes per requirement, task basis, ⚠ for ungrounded items); uncertainty (hour ranges as bars, confidence with rationale, open questions as "ask the client" actions); transparency (inspector, AI disclosure); recoverable errors mapped from the error taxonomy; onboarding via sample transcripts.
- Visual direction: sober enterprise (Linear, Stripe, IBM Carbon dashboards). One primary action per screen; hierarchy by size and weight, not colour; type scale 12/14/16/20/24; 4/8 px spacing grid; neutral palette with one accent; semantic colour only for states; `tabular-nums`, right-aligned numbers; dense, scannable tables; light and dark themes; responsive down to 360 px (inspector becomes a sheet).
- Motion: functional only (state transitions ≤ 150 ms), disabled under `prefers-reduced-motion`. Live regions: `aria-live="polite"` on status and completion, never per token. Visible focus, managed focus after actions.
- Skills to use while building: `frontend-design` (constrained to the sober direction above), `vercel:shadcn`, `vercel:nextjs`, `vercel:react-best-practices`, `a11y-debugging`; `gsd-ui-review` audit at branch end.

## 9. Definition of done (every branch)

1. `make check` green: ruff, mypy strict, pytest (offline), OpenSpec validation, OpenAPI snapshot current, web lint + typecheck + unit tests.
2. `docker compose up --build --wait` healthy; Playwright e2e against the `replay` provider (zero spend) passes, with zero serious or critical axe violations; screenshots and a GIF saved to `docs/media/session-0N/` and linked from the README.
3. Live checks within the budget (D12): S3 one streamed estimate per provider and a forced fallback; S4 eval gate (§6.4); S5 one three-turn live session with a PDF.
4. Review panel: parallel reviewers for AI-service correctness, streaming/cancellation/concurrency, security (injection, uploads, secrets, BFF request forwarding), UI/accessibility/visual hierarchy; each finding verified adversarially; confirmed findings fixed and re-checked.
5. Brief checklist mapped item by item to evidence in the README.
6. Affected `openspec/specs/*/spec.md` updated (D11); `make specs` green.
7. `docs/takeaways/session-0N.md`: per topic the concept, why it exists, trade-offs, alternatives with greater benefit and when to switch; ends with 6–8 quiz questions with answers in `<details>`. Passed through the `humanizer` skill.
8. Branch pushed (`git push -u origin pre-session-0N`, never forced); `PROGRESS.md` updated.

## 10. Out of scope

Semantic cache and output guardrails beyond M1's (session 4 live); authentication; Postgres; deployment; cumulative-summary or anchor memory, dynamic tier, Actor-Critic-Boss (session 5 live); manual task editing with recalculation; thumbs-up/down feedback loop; side-by-side prompt comparison UI. They appear in the takeaways as alternatives where relevant.

## 11. Operating rules for the implementation session

- Never read, print or commit `.env` (a permission rule denies reading `.env*`; `.env.example` is committed and can be read with `git show HEAD:.env.example` and rewritten from a shell heredoc).
- Never write to `main`, never force-push, never `git reset --hard`, never `rm -rf`.
- Verify library usage against `.claude/stack.md`; when it does not cover something, use Context7 and the installed package, then update the brief.
- Tests never call real LLMs; live calls only through the budget-guarded make targets.
- State lives in `docs/catch-up/PROGRESS.md`; every completed task is committed and recorded there before the next one starts.
