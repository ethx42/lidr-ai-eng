## 1. Toolchain and dependencies (`build:` commit)

- [x] 1.1 Add a failing test that every third-party import in `app/` is a direct `[project].dependencies` entry (D5). Verify it fails naming `httpx2`, `pydantic`, and `starlette`
- [x] 1.2 Move `httpx2` from the dev group to `[project].dependencies`, declare `pydantic` and `starlette` directly, and re-lock. Verify the 1.1 test passes and `uv.lock` versions are unchanged
- [x] 1.3 Add a failing structure test asserting `[tool.uv] required-version` in `pyproject.toml` and `UV_LOCKED: "1"` in the CI job env (D6). Then add both, upgrade local uv with `uv self update`, and re-lock with the pinned uv. Verify `uv --version` is within the range, `uv sync --locked` succeeds, and the test passes
- [x] 1.4 `make check` exits 0

## 2. Gate strictness (`chore:` commit)

- [x] 2.1 Migrate to a native `[tool.pytest]` table with `strict = true` and `asyncio_default_fixture_loop_scope = "function"`. Verify the pytest header reports `asyncio_default_fixture_loop_scope=function`, the suite passes with `-W error::pytest.PytestDeprecationWarning -W error::pytest.PytestConfigWarning`, and an unknown key is rejected
- [x] 2.2 Switch ruff to `extend-select` and drop `target-version`. Fix the new findings. Verify `uv run ruff check .` and `ruff format --check .` pass
- [x] 2.3 Enable `warn_unreachable`, the extra error codes, and the `[tool.pydantic-mypy]` flags (D7). Fix the findings. Verify `uv run mypy` passes
- [x] 2.4 `make check` exits 0

## 3. Anthropic context-window truncation (`fix:` commit)

- [x] 3.1 Add a failing provider test (stubbed client, like the existing Anthropic tests) where the Anthropic response has `stop_reason: "model_context_window_exceeded"` with a parseable body. Verify it expects `InvalidModelOutput`
- [x] 3.2 Add the stop reason to `INVALID_STOP_REASONS`. Verify the test passes and `make check` exits 0

## 4. Prompt cache routing and cache write tokens (`feat:` commit)

- [x] 4.1 Add failing tests: the OpenAI request body carries `prompt_cache_key == "estimator-<version>"` and is identical across two calls. The service passes a key that changes with the prompt version. The Anthropic request body carries no routing key
- [x] 4.2 Add failing tests: `Usage.cache_write_tokens` is mapped from OpenAI `input_tokens_details.cache_write_tokens` and Anthropic `cache_creation_input_tokens` (0 when absent), and appears in the `llm_call` log record, the API `usage`, and the eval case usage
- [x] 4.3 Implement D1/D2: the `cache_key` keyword on `LLMProvider.generate` (fake provider included), the `Usage` field, provider mappings, and the OpenAPI example. Verify the 4.1/4.2 tests pass and `make check` exits 0

## 5. Reasoning effort levels (`feat:` commit)

- [x] 5.1 Run a live one-token probe per profiled reasoning family and effort level (scratchpad script, `env -u ANTHROPIC_API_KEY`, keys from `.env`). Record accepted levels per family and the date. Verify each family has a level set (or is marked unverified)
- [x] 5.2 Add failing tests: settings accept all seven levels and reject `extreme` naming `LLM_REASONING_EFFORT`. `max` on `claude-opus-5` is sent as `output_config.effort`. `minimal` on `claude-opus-5` sends no effort or thinking and logs a warning naming the model, level, and supported levels. Haiku maps `xhigh`/`max` to budgets. gpt-5 family levels follow the probe
- [x] 5.3 Implement D4 (`ReasoningEffort` union, `ModelProfile.efforts`, budget map, warning in `get_profile`). Update the README effort docs. Verify the tests pass and `make check` exits 0. (`.env.example` left unchanged: the agent's permissions deny reading `.env*` files. It already lists the variable, so only its comment could be stale. Flagged for the user.)

## 6. Schema and API polish (`refactor:` commit)

- [x] 6.1 Add a test pinning the hash of `EstimationBreakdown.model_json_schema()` to its current value. Verify it passes before refactoring
- [x] 6.2 Move single-field rules to `AfterValidator` (D8). Update the schema tests for the new messages and `loc`. Verify the schema-hash test still passes
- [x] 6.3 Router: drop `response_model=`, add the `ServiceDep`/`SettingsDep` aliases, and state the JSON content type in the endpoint description. Add a test that a `text/plain` post returns `422 invalid_request` with no provider call. Verify the OpenAPI response schema for `/api/v1/estimate` is unchanged
- [x] 6.4 README: Content-Type note and production `uvicorn app.main:create_app --factory ...` command. Verify the factory starts with `uv run uvicorn app.main:create_app --factory` and `/health` returns 200
- [x] 6.5 `make check` exits 0

## 7. Live verification and docs (`docs:` commit)

- [ ] 7.1 Run `make eval` on `openai/gpt-4o-mini` (`env -u ANTHROPIC_API_KEY`). Verify cases after the first report `cached_input_tokens > 0`, or record why not. Verify `score` is not below the v4 baseline (0.9787)
- [ ] 7.2 Commit the report, add an eval-history row and caching note to the README, and update `.claude/stack.md` (resolved findings, probe results, caching outcome). Verify `make check` exits 0
