## 1. Project foundation

- [ ] 1.1 Initialize uv project (`pyproject.toml`, Python 3.12, runtime + dev deps, ruff/mypy/pytest config) and verify `uv sync` succeeds and `uv.lock` is created
- [ ] 1.2 Create brief-required skeleton (`app/`, `routers/`, `services/`, `context/` with `__init__.py`), `.gitignore` (incl. `.env`), `.env.example` with every variable, and verify `git check-ignore .env` succeeds
- [ ] 1.3 Extend the existing `Makefile` (`specs`, `openspec-sync` already present) with `install, run, test, lint, typecheck, check, eval`; verify `make lint` runs clean on the empty skeleton and the `.claude/settings.json` ruff hook formats an edited `.py` file
- [ ] 1.4 Add structure and secret-hygiene tests (`tests/test_structure.py`) and verify they pass and fail when a required file is temporarily removed

## 2. Configuration

- [ ] 2.1 Implement `Settings` with defaults, `SecretStr` keys, provider-key validator, and extra tunables; verify unit tests for defaults, missing-key failure naming the variable, and masked repr

## 3. Estimation contract and math

- [ ] 3.1 Implement `schemas/estimation.py` (`EstimateRequest`, `EstimationBreakdown` with field descriptions and three-point validators, enriched response models); verify unit tests for validation rules and that the JSON schema has no recursion/unsupported keywords
- [ ] 3.2 Implement `services/estimation_math.py` (PERT, totals, range, duration, cost); verify unit tests including the (8,10,18)+(20,30,40) → 41.0 scenario
- [ ] 3.3 Implement `services/grounding.py` (normalization, evidence check, basis check, report); verify unit tests for fabricated requirement, formatting-only differences, dangling basis, and empty requirements (score 1.0)
- [ ] 3.4 Implement `services/rendering.py` (markdown from enriched breakdown, ⚠ marks and grounding warnings section); verify tests that rendered total equals computed total and ungrounded items are marked

## 4. CAG prompt and context

- [ ] 4.1 Write three typed reference estimations in `context/examples.py` (small/medium/large, different domains); verify each validates against `EstimationBreakdown` and scores 1.0 grounding against its own meeting summary
- [ ] 4.2 Write `prompts/v1/system.md` and `prompts/loader.py` (version, deterministic rendering of references); verify tests: all references present in system text, system text identical across requests, pinned hash of rendered prompt
- [ ] 4.3 Implement user-message builder (delimited transcript + output-language directive); verify tests for explicit language and mirror-transcript default

## 5. LLM providers

- [ ] 5.1 Re-verify current OpenAI Responses and Anthropic Messages `parse` signatures via Context7 and record any deviation from design D3
- [ ] 5.2 Implement `providers/base.py` (Protocol, `LLMResult`, `Usage`) and `services/errors.py`; add `tests/fakes.py` `FakeProvider`; verify mypy strict passes
- [ ] 5.3 Implement `providers/profiles.py` (registry, prefix matching, conservative fallback + warning) and settings `LLM_REASONING_EFFORT`; verify parametrized tests of request kwargs per profile (gpt-4o-mini, gpt-5 family, claude-haiku-4-5, claude-opus-5, unknown)
- [ ] 5.4 Implement OpenAI adapter (`responses.parse`, profile-driven params, usage incl. cached tokens, incomplete/None → `InvalidModelOutput`, SDK error mapping); verify unit tests with mocked SDK client
- [ ] 5.5 Implement Anthropic adapter (`messages.parse`, profile-driven params, cached system block, refusal/max_tokens → `InvalidModelOutput`, SDK error mapping); verify unit tests with mocked SDK client
- [ ] 5.6 Implement provider factory and structured `llm_call` logging without transcript content; verify tests for selection and a log record that excludes transcript text

## 6. Service and HTTP API

- [ ] 6.1 Implement `EstimationService` in `services/llm_service.py` (prompt → provider → totals → grounding → render → response); verify unit tests with `FakeProvider`
- [ ] 6.2 Implement `create_app` with lifespan (client created once, closed on shutdown), request-id middleware, error handlers, `/health`, OpenAPI metadata; verify API tests for `/health` 200, `/docs` 200, `X-Request-ID` propagation
- [ ] 6.3 Implement `POST /api/v1/estimate` router; verify API tests for success, 422 cases (empty, too long, extra field, no provider call), and each upstream error mapping (429/503/502)

## 7. Evaluation

- [ ] 7.1 Add golden transcripts (`evals/golden/`: course transcript, well-specified medium, vague) and `data/transcripts/course-meeting.md`; verify files load in a unit test
- [ ] 7.2 Implement `evals/run_eval.py` (checks incl. grounding score/pass, summary table, versioned JSON report); verify with `FakeProvider` in a test and one real `make eval` run producing a report

## 8. CI, docs, and delivery

- [ ] 8.1 Add `.github/workflows/ci.yml` (single job: setup-uv → `uv sync --locked` → `make check`); verify `make check` passes locally and the workflow passes on push
- [ ] 8.2 Rewrite README (overview, architecture, brief-step → file map, setup, run, curl example, evals, verification checklist mapping); verify all commands in it run as written
- [ ] 8.3 Run the brief's verification checklist manually against a real provider (`uv run uvicorn app.main:app --reload`, curl, `/docs`) and record results in the README
- [ ] 8.4 Run `openspec validate add-cag-estimator --strict`, push `feat/m1-cag-estimator`, and share the branch URL
