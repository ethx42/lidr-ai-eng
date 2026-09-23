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

Behavior is specified in [`openspec/specs/`](openspec/specs/) (archived from [`openspec/changes/`](openspec/changes/)); the design rationale is in the change's `design.md`.

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
| `LLM_REASONING_EFFORT` | unset | `low`/`medium`/`high`, sent only to reasoning models |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_OUTPUT_TOKENS` | `30`, `2`, `4096` | |
| `MAX_TRANSCRIPTION_CHARS` | `50000` | longer requests get `422` |
| `BLENDED_HOURLY_RATE`, `WEEKLY_CAPACITY_HOURS` | unset, `30` | cost and duration estimates |

Environment variables override `.env`. If your shell exports an `ANTHROPIC_API_KEY` (for example inside Claude Code), it wins over the one in `.env`.

## Run

```bash
make run                # uv run uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: `curl http://127.0.0.1:8000/health`

```bash
curl -s http://127.0.0.1:8000/api/v1/estimate \
  -H 'Content-Type: application/json' \
  -d "$(jq -Rs '{transcription: .}' data/transcripts/course-meeting.md)" \
  | jq -r .estimation
```

Response fields: `estimation` (markdown), `breakdown` (structured, with computed `totals`), `grounding`, `model`, `provider`, `prompt_version`, `usage`. Optional request field: `output_language` (defaults to the transcription's language). Errors use `{"error": {"code", "message"}, "request_id"}`: `422 invalid_request`, `429 upstream_rate_limited`, `502 invalid_model_output` / `upstream_error` (also for exhausted provider quota, which is not retried), `503 upstream_unavailable`. Every response carries `X-Request-ID`.

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
| **v4** `openai/gpt-4o-mini` ([baseline](evals/baseline.json)) | 0.9787 (46/47) | 0.80 | grounding 1.0 and correct language on all cases; vague case missed a devops task |
| v3 `openai/gpt-4o-mini` ([report](evals/reports/v3-20260923T134157Z.json)) | 0.9362 (44/47) | 0.40 | evidence fixed, but English transcripts got Spanish narrative |
| v2 `openai/gpt-4o-mini` ([report](evals/reports/v2-20260923T133936Z.json)) | 0.9787 (46/47) | 0.80 | evidence translated under an explicit Spanish output |
| v1 `openai/gpt-4o-mini` ([report](evals/reports/v1-20260923T131705Z.json)) | 0.9118 (31/34) | 0.50 | paraphrased evidence; no language check yet |
| v1 `anthropic/claude-haiku-4-5` ([report](evals/reports/v1-20260923T131013Z.json)) | 0.9706 (33/34) | 0.75 | grounding 1.0; ~8k of ~8.3k input tokens served from prompt cache |

Prompt versions live in `app/prompts/<version>/`; the rationale and expected eval impact of each version are in the change's `design.md` (D4).

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
