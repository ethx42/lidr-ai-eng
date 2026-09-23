## 1. Project foundation
Depends on: none
Paths: pyproject.toml, uv.lock, Makefile, .gitignore, .env.example, app/__init__.py, app/routers/__init__.py, app/services/__init__.py, app/context/__init__.py, tests/__init__.py, tests/test_structure.py

- [x] 1.1 Initialize uv project (`pyproject.toml`, Python 3.12, runtime + dev deps, ruff/mypy/pytest config) and verify `uv sync` succeeds and `uv.lock` is created
- [x] 1.2 Create brief-required skeleton (`app/`, `routers/`, `services/`, `context/` with `__init__.py`), `.gitignore` (incl. `.env`), `.env.example` with every variable, and verify `git check-ignore .env` succeeds
- [x] 1.3 Extend the existing `Makefile` (`specs`, `openspec-sync` already present) with `install, run, test, lint, typecheck, check, eval, eval-baseline`; verify `make lint` runs clean on the empty skeleton and the `.claude/settings.json` ruff hook formats an edited `.py` file
- [x] 1.4 Add structure and secret-hygiene tests (`tests/test_structure.py`) and verify they pass and fail when a required file is temporarily removed

## 2. Configuration
Depends on: 1
Paths: app/config.py, tests/unit/test_config.py

- [x] 2.1 Implement `Settings` with defaults, `SecretStr` keys, provider-key validator, and extra tunables; verify unit tests for defaults, missing-key failure naming the variable, and masked repr

## 3. Estimation contract and math
Depends on: 1, 2
Paths: app/schemas/**, app/services/estimation_math.py, app/services/grounding.py, app/services/rendering.py, tests/unit/test_schemas.py, tests/unit/test_estimation_math.py, tests/unit/test_grounding.py, tests/unit/test_rendering.py

- [x] 3.1 Implement `schemas/estimation.py` (`EstimateRequest`, `EstimationBreakdown` with field descriptions and three-point validators, enriched response models); verify unit tests for validation rules and that the JSON schema has no recursion/unsupported keywords
- [x] 3.2 Implement `services/estimation_math.py` (PERT, totals, range, duration, cost); verify unit tests including the (8,10,18)+(20,30,40) → 41.0 scenario
- [x] 3.3 Implement `services/grounding.py` (normalization, evidence check, basis check, report); verify unit tests for fabricated requirement, formatting-only differences, dangling basis, and empty requirements (score 1.0)
- [x] 3.4 Implement `services/rendering.py` (markdown from enriched breakdown, ⚠ marks and grounding warnings section); verify tests that rendered total equals computed total and ungrounded items are marked

## 4. CAG prompt and context
Depends on: 3
Paths: app/context/examples.py, app/prompts/**, tests/unit/test_examples.py, tests/unit/test_prompts.py

- [x] 4.1 Write three typed reference estimations in `context/examples.py` (small/medium/large, different domains); verify each validates against `EstimationBreakdown` and scores 1.0 grounding against its own meeting summary
- [x] 4.2 Write `prompts/v1/system.md` and `prompts/loader.py` (version, deterministic rendering of references); verify tests: all references present in system text, system text identical across requests, pinned hash of rendered prompt
- [x] 4.3 Implement user-message builder (delimited transcript + output-language directive); verify tests for explicit language and mirror-transcript default

## 5. LLM providers
Depends on: 2, 3
Paths: app/services/providers/**, app/services/errors.py, app/observability.py, app/config.py, tests/fakes.py, tests/unit/providers/**, tests/unit/test_observability.py

- [x] 5.1 Re-verify current OpenAI Responses and Anthropic Messages `parse` signatures via Context7 and record any deviation from design D3
- [x] 5.2 Implement `providers/base.py` (Protocol, `LLMResult`, `Usage`) and `services/errors.py`; add `tests/fakes.py` `FakeProvider`; verify mypy strict passes
- [x] 5.3 Implement `providers/profiles.py` (registry, prefix matching, conservative fallback + warning) and settings `LLM_REASONING_EFFORT`; verify parametrized tests of request kwargs per profile (gpt-4o-mini, gpt-5 family, claude-haiku-4-5, claude-opus-5, unknown)
- [x] 5.4 Implement OpenAI adapter (`responses.parse`, profile-driven params, usage incl. cached tokens, incomplete/None → `InvalidModelOutput`, SDK error mapping); verify unit tests with mocked SDK client
- [x] 5.5 Implement Anthropic adapter (`messages.parse`, profile-driven params, cached system block, refusal/max_tokens → `InvalidModelOutput`, SDK error mapping); verify unit tests with mocked SDK client
- [x] 5.6 Implement provider factory and structured `llm_call` logging without transcript content; verify tests for selection and a log record that excludes transcript text

## 6. Service and HTTP API
Depends on: 4, 5
Paths: app/services/llm_service.py, app/main.py, app/routers/estimations.py, tests/unit/test_llm_service.py, tests/api/**

- [x] 6.1 Implement `EstimationService` in `services/llm_service.py` (prompt → provider → totals → grounding → render → response); verify unit tests with `FakeProvider`
- [x] 6.2 Implement `create_app` with lifespan (client created once, closed on shutdown), request-id middleware, error handlers, `/health`, OpenAPI metadata; verify API tests for `/health` 200, `/docs` 200, `X-Request-ID` propagation
- [x] 6.3 Implement `POST /api/v1/estimate` router; verify API tests for success, 422 cases (empty, too long, extra field, no provider call), and each upstream error mapping (429/503/502)

## 7. Evaluation
Depends on: 6
Paths: evals/**, data/transcripts/**, Makefile, tests/unit/test_eval.py

- [ ] 7.1 Add golden transcripts (`evals/golden/`: course transcript, well-specified medium, vague) and `data/transcripts/course-meeting.md`; verify files load in a unit test
- [ ] 7.2 Implement `evals/run_eval.py` (checks incl. grounding score/pass, summary table, versioned JSON report with top-level `score` = checks passed ÷ checks run, `--report <path>`); verify with `FakeProvider` tests for score granularity and explicit path, and one real `make eval` run producing a report
- [ ] 7.3 Record the first baseline with `make eval-baseline` (report → `evals/baseline.json`, committed); verify the file contains `score`, prompt version, provider, and model

## 8. CI, docs, and delivery
Depends on: 7
Paths: .github/workflows/ci.yml, README.md, AGENTS.md, openspec/**

- [ ] 8.1 Add `.github/workflows/ci.yml` (single job: setup-uv → `uv sync --locked` → `make check`); verify `make check` passes locally and the workflow passes on push
- [ ] 8.2 Update `AGENTS.md` step 5 and `openspec/config.yaml` archive guidance to archive-before-merge (archive on the change branch before hand-off); verify `make specs` passes
- [ ] 8.3 Rewrite README (overview, architecture, brief-step → file map, setup, run, curl example, evals, verification checklist mapping); verify all commands in it run as written
- [ ] 8.4 Run the brief's verification checklist manually against a real provider (`uv run uvicorn app.main:app --reload`, curl, `/docs`) and record results in the README
- [ ] 8.5 Hand off: `openspec validate add-cag-estimator --strict` → `/opsx:verify` (no gaps) → `openspec archive add-cag-estimator --yes` → `make check` (incl. `make specs`: main specs valid, archived change has no open tasks) → push `feat/m1-cag-estimator` and share the branch URL
