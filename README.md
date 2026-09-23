# lidr-ai-eng

Project for the LIDR AI Engineering course, grown one milestone per course brief.

**M1 — CAG software estimator.** A FastAPI service that turns a meeting transcription into a software estimation produced by an LLM, using Cache-Augmented Generation: all reference context (three typed past estimations) travels inside a cache-stable system prompt, with no database or retrieval. The model returns a structured breakdown; totals, grounding checks, and the markdown report are computed in code.

## Architecture

```
POST /api/v1/estimate
  └─ routers/estimations.py        validate request (422 before any LLM call)
      └─ services/llm_service.py   EstimationService
          ├─ prompts/loader.py     v1 system prompt + reference estimations (byte-stable, cacheable)
          │                        user message: <transcript> + <output_language>
          ├─ services/providers/   OpenAI Responses `parse` | Anthropic Messages `parse`
          │                        (structured output, per-model request profiles, SDK retries)
          ├─ estimation_math.py    PERT expected hours, totals, range, duration, cost
          ├─ grounding.py          evidence quotes checked against the transcript; task basis checked
          └─ rendering.py          markdown with ⚠ marks and a grounding warnings section
```

Behavior is specified in [`openspec/specs/`](openspec/specs/); the change that introduced it, with its design rationale, is archived in [`openspec/changes/archive/2026-09-23-add-cag-estimator/`](openspec/changes/archive/2026-09-23-add-cag-estimator/) ([design](openspec/changes/archive/2026-09-23-add-cag-estimator/design.md)). Stack hardening after M1 (prompt-cache routing, effort levels per model, stricter gates) is archived in [`2026-09-23-harden-stack-usage/`](openspec/changes/archive/2026-09-23-harden-stack-usage/) ([design](openspec/changes/archive/2026-09-23-harden-stack-usage/design.md)).

### Brief step → files

| Brief step | Files |
|---|---|
| Project structure | `app/`, `app/routers/`, `app/services/`, `app/context/` (checked by `tests/test_structure.py`) |
| Configuration and `.env` | `app/config.py`, `.env.example`, `.gitignore` |
| Reference estimations (≥ 2 examples) | `app/context/examples.py` (small, medium, large) |
| LLM service | `app/services/llm_service.py`, `app/services/providers/`, `app/prompts/` |
| Estimate endpoint | `app/routers/estimations.py`, `app/schemas/estimation.py` |
| Application and docs | `app/main.py` (`/health`, `/docs`) |
| Meeting transcription | `data/transcripts/course-meeting.md` |

Extra folders: `app/schemas/` (request/response and LLM output contract), `app/prompts/` (versioned prompt as data), `evals/` (live prompt evaluation), `tests/` (offline test suite), `openspec/` (specs and change history).

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned and installed by uv) and Node (only for `make specs`).

```bash
make install            # uv sync
cp .env.example .env    # then set LLM_PROVIDER, LLM_MODEL, and the matching API key
```

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` or `anthropic` |
| `LLM_MODEL` | `gpt-4o-mini` | e.g. `claude-haiku-4-5`; server-side only |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | required for the selected provider; startup fails naming the missing one |
| `LLM_TEMPERATURE` | `0.2` | sent only to models that support it |
| `LLM_REASONING_EFFORT` | unset | `none`/`minimal`/`low`/`medium`/`high`/`xhigh`/`max`; sent only to reasoning models that accept that level (others get no effort and a startup warning listing the supported levels) |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_OUTPUT_TOKENS` | `60`, `2`, `4096` | timeout is per attempt; reasoning models may need more |
| `MAX_TRANSCRIPTION_CHARS` | `50000` | longer requests get `422` |
| `BLENDED_HOURLY_RATE`, `WEEKLY_CAPACITY_HOURS` | unset, `30` | cost and duration estimates |
| `APP_ENV`, `LOG_LEVEL` | `development`, `DEBUG` | JSON logs on stderr; see Logging below |

**Logging.** `LOG_LEVEL` applies to the app's own loggers. The client libraries (`anthropic`, `openai`, `httpx2`, `httpcore2`) are kept at `INFO` or above whatever the level, because at `DEBUG` the Anthropic SDK logs request bodies, which contain the transcription. No log record contains the transcription or API keys. Each LLM call writes one `llm_call` record (provider, model, prompt version, token counts, latency, outcome). A failed call also carries `cause` (the stop condition, e.g. `stop_reason:max_tokens`, or the upstream error class) and `upstream_status`, never the provider's message. Unhandled errors log the exception type and stack locations, not the message.

Environment variables override `.env`. If your shell exports an `ANTHROPIC_API_KEY` (for example inside Claude Code), it wins over the one in `.env`.

## Run

```bash
make run                # uv run uvicorn app.main:app --reload
```

Production (no `--reload`; the app factory reads settings from the environment):

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 \
  --workers 4 --forwarded-allow-ips <proxy CIDR> --timeout-graceful-shutdown 30
```

- API docs: http://127.0.0.1:8000/docs
- Health: `curl http://127.0.0.1:8000/health`

```bash
curl -s http://127.0.0.1:8000/api/v1/estimate \
  -H 'Content-Type: application/json' \
  -d "$(jq -Rs '{transcription: .}' data/transcripts/course-meeting.md)" \
  | jq -r .estimation
```

Requests must be sent with `Content-Type: application/json`; other content types get `422 invalid_request`. Response fields: `estimation` (markdown), `breakdown` (structured, with computed `totals`), `grounding`, `model`, `provider`, `prompt_version`, `usage` (`input_tokens`, `output_tokens`, `cached_input_tokens`, `cache_write_tokens`). Optional request field: `output_language` (defaults to the transcription's language). Errors use `{"error": {"code", "message"}, "request_id"}`: `422 invalid_request`, `429 upstream_rate_limited`, `502 invalid_model_output` / `upstream_error` (also for exhausted provider quota, which is not retried), `503 upstream_unavailable`. Every response carries `X-Request-ID`.

## Quality gates

```bash
make check              # lint → typecheck → tests → specs (same as CI)
```

Tests are offline (a fake provider, SDK clients on a mock transport); they never call a real LLM. CI (`.github/workflows/ci.yml`) runs `make check` on every push and pull request.

## Evaluation

```bash
make eval                               # live run over evals/golden/*.md with the configured provider
make eval REPORT=path/to/report.json    # write the report to an explicit path
make eval-baseline [REPORT=...]         # copy a report (default: latest) to evals/baseline.json
```

The golden set (`evals/golden/`) has five transcriptions: the course meeting, a well-specified medium project, a vague idea, a Spanish one with an injected instruction, and an English one evaluated with `output_language: Spanish` (declared in front matter). Each case records schema validity, three-point ordering, hours within 4–80, coverage of QA/devops/project management, grounding (evidence verbatim in the transcript, valid task basis), narrative language (the declared `output_language`, otherwise the transcript's language), open questions and confidence for the vague case, latency, and token usage including cached tokens. `score` = checks passed ÷ checks run.

| Run | Score | Case pass rate | Notes |
|---|---|---|---|
| v4 `openai/gpt-4o-mini` + `prompt_cache_key` ([report](evals/reports/v4-20260923T145152Z.json)) | 1.0 (47/47) | 1.00 | same prompt as the baseline (score gain is sampling variance); prompt cache now hits: cases 2–5 read 6016 of ~6400 input tokens from cache (baseline: 0) |
| **v4** `openai/gpt-4o-mini` ([baseline](evals/baseline.json)) | 0.9787 (46/47) | 0.80 | grounding 1.0 and correct language on all cases; vague case missed a devops task |
| v3 `openai/gpt-4o-mini` ([report](evals/reports/v3-20260923T134157Z.json)) | 0.9362 (44/47) | 0.40 | evidence fixed, but English transcripts got Spanish narrative |
| v2 `openai/gpt-4o-mini` ([report](evals/reports/v2-20260923T133936Z.json)) | 0.9787 (46/47) | 0.80 | evidence translated under an explicit Spanish output |
| v1 `openai/gpt-4o-mini` ([report](evals/reports/v1-20260923T131705Z.json)) | 0.9118 (31/34) | 0.50 | paraphrased evidence; no language check yet |
| v1 `anthropic/claude-haiku-4-5` ([report](evals/reports/v1-20260923T131013Z.json)) | 0.9706 (33/34) | 0.75 | grounding 1.0; ~8k of ~8.3k input tokens served from prompt cache |

OpenAI requests carry `prompt_cache_key=estimator-<prompt version>` so calls sharing the system prompt are routed to the same cache; `usage.cache_write_tokens` reports cache writes where the provider exposes them (Anthropic always, OpenAI gpt-4o-mini reports 0).

Prompt versions live in `app/prompts/<version>/`; the rationale and expected eval impact of each version are in the archived [design](openspec/changes/archive/2026-09-23-add-cag-estimator/design.md) (D4).

The eval is never part of `make check` or CI.

## Verification checklist

Run manually on 2026-09-23 against `openai/gpt-4o-mini`, prompt v4.

| Check | How | Result |
|---|---|---|
| Server starts | `uv run uvicorn app.main:app --reload` | ✅ starts; settings validated at startup |
| Health | `GET /health` | ✅ `200`, `status: ok`, provider/model reported, `X-Request-ID` set |
| Interactive docs | `GET /docs`, `GET /openapi.json` | ✅ `200` |
| Estimation from the course transcript | `POST /api/v1/estimate` (curl above) | ✅ `200` in 14 s; English narrative; 10/10 requirements grounded; 268.5 h expected (168–415 h); no transcript text in logs |
| Invalid request | `POST` with blank transcription | ✅ `422 invalid_request`, no LLM call |
| Secrets | `.env` ignored by git; keys masked in settings | ✅ `tests/test_structure.py`, `tests/unit/test_config.py` |

Known limitations (candidates for the next prompt version or milestone):
- The course estimate still has no `frontend` tasks for the member app and staff panel, despite v4's per-surface rule; the eval does not check surface coverage yet.
- Duration (1–2 weeks for a team of 7) is total hours ÷ team capacity, a bound that ignores sequencing.
- `gpt-4o-mini` occasionally drops the devops task on vague input (v2 included it, v4 did not).
- OpenAI reported `cached_input_tokens: 0` on every call despite the byte-stable prefix; Anthropic caching engages.
