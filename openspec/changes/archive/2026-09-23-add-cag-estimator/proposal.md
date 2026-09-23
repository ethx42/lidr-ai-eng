## Why

Milestone 1 of the LIDR AI Engineering program asks for a FastAPI service that turns a meeting transcription into a software estimation produced by an LLM, using a CAG (Cache-Augmented Generation) architecture: all reference context travels inside the prompt, with no database or retrieval. The repository is empty, and this first deliverable must also set up the foundation (spec-driven workflow, quality gates, CI) that later milestones — RAG, evaluation, and beyond — will build on.

## What Changes

- Scaffold a uv-managed Python 3.12 FastAPI project that keeps every path required by the course brief (`app/main.py`, `app/config.py`, `app/routers/estimations.py`, `app/services/llm_service.py`, `app/context/examples.py`, `.env.example`, …).
- Add `POST /api/v1/estimate`: accepts a transcription (plus optional `output_language`) and returns a rendered markdown estimation, a structured breakdown, model, provider, prompt version, and token usage.
- Add `GET /health` and OpenAPI docs at `/docs`.
- Support both OpenAI (Responses API) and Anthropic (Messages API) behind one provider interface, selected by `LLM_PROVIDER`, each using native structured outputs.
- Add a versioned system prompt with typed few-shot reference estimations (the CAG context), laid out so the stable prefix can be prompt-cached.
- Verify grounding in code: every requirement carries a verbatim evidence quote checked against the transcript, every task cites the requirements/assumptions it rests on, and a grounding report flags anything unsupported.
- Shape each provider request by a per-model capability profile (sampling vs. reasoning parameters) so any configured model gets the parameters it supports.
- Compute all totals (PERT expected hours, ranges, optional cost) deterministically in code; the model never does arithmetic.
- Add environment-driven configuration with secrets that are never logged or committed.
- Add an opt-in live evaluation harness over a small golden set of transcripts, producing a JSON report per prompt version.
- Add quality gates: ruff, mypy, pytest (unit, API, project-structure checks) with a fake provider, `openspec validate`, and a single concise GitHub Actions workflow.
- Add the course meeting transcription used as the exercise input, README, and agent guidance (English-only, spec-first).

Deferred to a later change: an interactive clarification round-trip where the API asks blocking questions before estimating.

## Capabilities

### New Capabilities
- `estimation-api`: HTTP contract for requesting an estimation from a transcription, the health endpoint, API documentation, and error semantics.
- `llm-providers`: Provider-agnostic generation of a structured estimation via OpenAI or Anthropic, including selection, timeouts, retries, and failure mapping.
- `prompt-context`: The CAG prompt: system instructions, injected reference estimations, transcript handling, output-language control, prompt versioning, and the estimation content contract.
- `configuration`: Environment-based settings, defaults, secret handling, and startup validation.
- `prompt-evaluation`: Opt-in live evaluation of prompt quality against golden transcripts with a persisted report.
- `quality-gates`: Automated checks that run on every push/PR — lint, types, tests, required project structure, secret hygiene, and spec validation.

### Modified Capabilities
<!-- None: this is the first change in the repository. -->

## Impact

- New code under `app/`, `tests/`, `evals/`, `data/transcripts/`; new `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, `.gitignore`, `.github/workflows/ci.yml`, `CLAUDE.md`/`AGENTS.md`, README rewrite.
- New runtime dependencies: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `openai`, `anthropic`, `python-dotenv`. Dev: `pytest`, `pytest-asyncio`, `httpx2`, `ruff`, `mypy`.
- External systems: OpenAI and Anthropic APIs (only at runtime and in `make eval`; never in CI).
- Delivered on branch `feat/m1-cag-estimator`; merged to `main` and tagged `m1` after review.
