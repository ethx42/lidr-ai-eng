## Context

See proposal.md for motivation. Every SDK and tool claim below was checked against the installed packages on 2026-09-23 (openai 3.19.0, anthropic 1.8.0, fastapi 0.141.1, pydantic 2.13.5, pytest 9.1.1, pytest-asyncio 1.4.0, ruff 0.16.8, mypy 2.3.1). The sources were `.claude/stack.md`, Context7 (`/websites/developers_openai_api`, `/anthropics/anthropic-sdk-python`, and the tool docs listed in the brief), and the installed signatures and types:

- `AsyncResponses.parse` accepts `prompt_cache_key: Optional[str]`.
- OpenAI `InputTokensDetails` has `cached_tokens` and `cache_write_tokens: int`.
- Anthropic `StopReason` includes `"model_context_window_exceeded"`. `Usage.cache_creation_input_tokens` is `int | None`.
- OpenAI `ReasoningEffort` = `none|minimal|low|medium|high|xhigh|max`. Anthropic `OutputConfigParam.effort` = `low|medium|high|xhigh|max`. Both docs state that per-model support varies.
- FastAPI 0.141.1 rejects a body sent as `text/plain` with `422` (`loc: ["body"]`, `type: model_attributes_type`) before the handler runs. This was checked with the app's own `TestClient`, and the fake provider saw no call.
- Local uv is 0.8.15 (standalone install in `~/.local/bin`). The latest release is 0.12.18.

## Goals / Non-Goals

**Goals:**
- Make OpenAI prompt caching measurable and give it a chance to hit. Verify with a live eval.
- Close the two correctness gaps: context-window truncation, and a runtime dependency declared as dev-only.
- Make the gates at least as strict as the installed tools allow, and fix what they find.

**Non-Goals:**
- Changing prompts, models, or defaults. The prompt version stays `v4`, and the eval score should not move.
- Adopting gpt-5.6+ cache options, Anthropic middleware, or the Models API (see proposal: Explicitly deferred).

## Decisions

### D1. The cache routing key is passed per call, derived by the service
`LLMProvider.generate` gains a `cache_key: str` keyword. `EstimationService` passes `f"estimator-{prompt.version}"`. OpenAI sends it as `prompt_cache_key`. Anthropic ignores it: its cache is keyed by content through the block-level `cache_control` marker, and the Messages API has no routing key.
- *Why:* the prompt version lives in the service (`PromptBundle`), and the provider is built before the prompt is loaded. Passing the key per call keeps providers free of prompt knowledge.
- *Rejected:* building the key inside the provider from a constructor argument, which means threading the prompt version through `build_provider`/`Settings` and couples provider construction to prompt loading. Also rejected: `safety_identifier`/`user`, which have a different purpose.
- `store=False` stays. The docs make caching independent of response storage.

### D2. `Usage` gains `cache_write_tokens`
One additive field with default `0`. OpenAI maps `input_tokens_details.cache_write_tokens`. Anthropic maps `cache_creation_input_tokens or 0`. `input_tokens` stays the total (Anthropic already sums the three parts). The log record and eval report pick the field up automatically through `Usage.model_dump()`. The OpenAPI example gains the field.
- *Rejected:* a nested `cache: {read, write}` object. It would break the existing flat `cached_input_tokens` contract.

### D3. Context-window stop is invalid output
`"model_context_window_exceeded"` joins `INVALID_STOP_REASONS`. It is checked before `parsed_output`, as `max_tokens` is today, so a parseable prefix is still rejected. OpenAI needs no change: exhaustion there surfaces as `status == "incomplete"`, which is already invalid.

### D4. Reasoning effort: SDK union in config, per-model levels in profiles, omit-and-warn
- `ReasoningEffort` becomes the OpenAI SDK union (the superset of both SDKs): `none|minimal|low|medium|high|xhigh|max`. Pydantic's `Literal` keeps the fail-fast error naming the variable.
- `ModelProfile` gains `efforts: frozenset[ReasoningEffort]`, the levels verified for that family. `request_params` sends effort only when `effort in profile.efforts`. `get_profile` (already called once at startup by the factory) logs one warning when a configured level is unsupported.
- Haiku 4.5 (budget thinking) maps the levels to budgets: `low` 2048, `medium` 4096, `high` 8192, `xhigh` 16384, `max` 32768. That is within its 64k output limit, and `max_tokens` still adds the budget.
- The per-family level sets are confirmed with a live probe: a one-token request per family and level, recording 200 vs 400. Levels the API rejects are left out of the profile. The probe script lives in the scratchpad, and its results and date go into the profile comment and `.claude/stack.md`.
- *Why omit-and-warn rather than fail fast:* the finding says "sent only where the model allows", and M1 already treats unsupported parameters this way (temperature, unknown models). A misconfiguration shows up in the startup log, not as a crash loop.
- *Rejected:* fail at startup for an unsupported level. It is safer for typos, but the `Literal` already catches typos. Also rejected: silently clamping to the nearest level, which would send something the operator did not ask for.

### D5. Guarding runtime imports: direct declaration
A test walks `app/**/*.py` with `ast` and collects top-level third-party module names (`sys.stdlib_module_names` excluded). It maps them to distributions with `importlib.metadata.packages_distributions()` and asserts each distribution is named in `[project].dependencies` of `pyproject.toml` (read with `tomllib`, names normalized per PEP 503).
- *Why direct, not the lockfile closure (revised during apply):* `httpx2` is already a transitive runtime dependency (openai 3.19.0 and anthropic 1.8.0 both require it), so a closure test would pass while the finding stands. The real gap is that the app imports it directly without stating which versions it supports. The same check found `pydantic` (through fastapi/pydantic-settings) and `starlette` (through fastapi). All three are declared directly with lower bounds at the installed versions (`httpx2>=2.13.0`, `pydantic>=2.13.5`, `starlette>=1.6.0`). This changes nothing at runtime.
- *Rejected:* a closure test over `uv.lock`, which misses the finding it exists for. Also rejected: an allowlist for framework re-exports (pydantic, starlette), which hides the same class of drift. And `uv sync --no-dev` + import smoke test in CI, which is slower and not caught by `make check`.

### D6. uv pin and CI locking
`[tool.uv] required-version = ">=0.12.18,<0.13"`. uv minor releases are breaking, and setup-uv reads this field to pick the version. CI sets `env: UV_LOCKED: "1"` at job level, so every `uv run`/`uv sync` asserts the lockfile instead of re-locking. `uv sync --locked` stays explicit. The local uv is upgraded with `uv self update` (standalone install), then `uv lock` is re-run so the lockfile is written by the pinned version. A test in `tests/test_structure.py` asserts both settings are present.

### D7. Gate strictness
- **pytest:** `[tool.pytest.ini_options]` becomes a native `[tool.pytest]` table with `strict = true` (strict config, markers, xfail, parametrize ids) and `asyncio_default_fixture_loop_scope = "function"`. Verification: `pytest` shows no warnings and does not fail on unknown keys (strict config catches those). If pytest-asyncio does not read the native table, fall back to `ini_options` for its keys only and record that here.
- **ruff:** `extend-select`, so the 0.16 default set is extended rather than replaced. `target-version` is removed because it is inferred from `requires-python`. New findings are fixed in code. A per-file ignore is used only where a rule conflicts with an intended pattern, and the reason is given inline.
- **mypy:** `warn_unreachable = true`, `enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool", "possibly-undefined"]`, and `[tool.pydantic-mypy] init_forbid_extra = true, init_typed = true, warn_required_dynamic_aliases = true`. New findings are fixed in code, not suppressed.

### D8. Schema and API polish without contract change
- Single-field rules become `Annotated[..., AfterValidator(fn)]`: non-blank evidence, `count >= 1`, non-empty basis, non-empty tasks, and the per-list identifier format. Cross-field rules (hour ordering and bounds) stay in `@model_validator`.
- **Contract:** `EstimationBreakdown.model_json_schema()` must be byte-identical before and after. A test pins it to a committed hash, so the LLM-facing schema cannot drift silently.
- Error messages lose the `T1:`/`R1:` prefix, because the `loc` carries the index. These errors are internal (mapped to `502`), so no API contract changes.
- The router drops `response_model=`, since the return annotation already defines the response. It uses `ServiceDep`/`SettingsDep` `Annotated` aliases.
- The `Content-Type: application/json` requirement goes in the endpoint `description` (OpenAPI) and the README. A test covers the `422`.
- The README production command is `uvicorn app.main:create_app --factory --workers N --forwarded-allow-ips <proxy CIDR> --timeout-graceful-shutdown 30`. `create_app()` works with no arguments (settings from the environment).

## Risks / Trade-offs

- [`prompt_cache_key` may still not produce hits on gpt-4o-mini, for example because of prefix length or routing] → the live eval decides. If cached tokens stay 0, report it, keep the key (harmless and recommended), and record the finding in `.claude/stack.md`. No spec depends on a hit, only on the key and the reporting.
- [The live effort probe costs a few cents and depends on account model access] → it runs once, with minimal tokens. A family the account cannot reach keeps the SDK-documented set and is marked "unverified" in the profile comment.
- [The stricter ruff/mypy sets may surface many findings] → the grounding run measured 3 ruff findings and 0 mypy findings on `app/`. If the real count is much larger, stop and update this design before fixing.
- [uv 0.8 → 0.12 changes the lockfile format] → re-lock in the tooling commit and check that `uv sync --locked` and the full `make check` pass with the new uv.

## Migration Plan

Additive only. Deploy as usual. Rollback is reverting the branch. `LLM_REASONING_EFFORT` values that worked before (`low|medium|high`) behave the same on every profiled model.
