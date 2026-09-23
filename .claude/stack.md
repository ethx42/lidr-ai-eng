# Tech stack brief

stack-fingerprint: fdb14250a109
updated: 2026-09-23

How the installed versions are meant to be used today. Read before writing code against them; update when you learn something new (`stack-grounding` skill). Installed versions win over memory and over docs for other versions.

## OpenAI Python 3.19.0
- **Use:** `await client.responses.parse(model, instructions=system, input=user, text_format=Model, store=False, ...)` → `output_parsed`. `status == "incomplete"` or `output_parsed is None` = invalid output; schema-invalid JSON raises `pydantic.ValidationError` inside `parse`. Never mix `text_format` with `text={"format": ...}`.
- **Patterns:** client-level `timeout`/`max_retries` (defaults 10 min / 2); per call `client.with_options(...)`. Catch `APIConnectionError` (incl. timeout) → `RateLimitError` → `APIStatusError`. SDK obeys `x-should-retry`; there is no middleware, so an httpx2 response hook is the place to stop retries on `insufficient_quota` 429s. Close with `await client.close()`.
- **Reasoning:** `reasoning={"effort": ...}` accepts `none|minimal|low|medium|high|xhigh|max` in the SDK, but models reject unsupported levels with 400. Live probe (2026-09-23): gpt-5/-mini/-nano `minimal..high`; gpt-5.1 `none,low..high`; gpt-5.2–5.5 add `xhigh`; gpt-5.6-* add `max`; o3/o4-mini `low..high`. `verbosity` is a top-level param.
- **New and useful:** `prompt_cache_key` groups requests sharing a prefix (≈15 req/min per key). Measured here: gpt-4o-mini went from 0 to 6016 of ~6400 input tokens cached on calls 2–5 once the key was set. `usage.input_tokens_details.cache_write_tokens` exists, but gpt-4o-mini reports 0 even on the first (writing) call. gpt-5.6+: `prompt_cache_options={mode, ttl, prewarm}` with explicit breakpoints; `responses.input_tokens.count(...)`.
- **Avoid:** `prompt_cache_retention` (deprecated → `prompt_cache_options.ttl`); `output_text` for structured results; `user=` (use `prompt_cache_key`/`safety_identifier`); Chat Completions `.parse` for new code.
- **Sources:** Context7 `/openai/openai-python` (lists ≤v2.11 but README is 3.x) + `/websites/developers_openai_api` (2026-09-23); installed signatures, `types/responses/*`, `_base_client.py` `_should_retry`.

## Anthropic Python 1.8.0
- **Use:** `await client.messages.parse(model, max_tokens, system=[{type:"text", text, cache_control:{type:"ephemeral"}}], messages=[...], output_format=Model)` → `parsed_output`. `output_format` takes a class only; raw schemas go in `output_config={"format": ...}`; `output_config={"effort": ...}` merges with it (`low|medium|high|xhigh|max`).
- **Patterns:** effort levels `low|medium|high|xhigh|max` all accepted by claude-sonnet-5, opus-5(-5), fable-5(-1) (live probe 2026-09-23). `stop_reason` includes `model_context_window_exceeded` (treat as truncation). thinking: `{"type":"adaptive"}` on newer models, `{"type":"enabled","budget_tokens":N}` on `claude-haiku-4-5`; `max_tokens` must cover thinking. Retries 408/409/429/5xx/connection with backoff; honours `retry-after(-ms)` and `x-should-retry`. `usage.input_tokens` excludes cache: total = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
- **New and useful:** `AsyncAnthropic(middleware=[...])` runs once per attempt inside the retry loop (cleaner than httpx hooks). `cache_control` `ttl: "5m"|"1h"`. `count_tokens(..., output_format=Model)`. Beta `diagnostics={"previous_message_id": ...}` returns `cache_miss_reason`. `Message.stop_details` for structured refusals.
- **Avoid:** `temperature`/`top_p`/`top_k` kwargs (removed → `TypeError`; older models such as Haiku 4.5 still honour them via `extra_body`). `parse(stream=True)` (use `messages.stream(output_format=...)`). Top-level `cache_control` is not accepted by `parse()`; keep the block-level marker.
- **Sources:** Context7 `/anthropics/anthropic-sdk-python` (tracks 1.x MIGRATION.md, 2026-09-23); installed signatures, `_middleware.py`, `types/*`, `_base_client.py`, mock-transport body capture.

## FastAPI 0.141.1 + Starlette 1.6.0
- **Use:** app factory + `lifespan=` context manager; `Annotated[T, Depends(fn)]` with reusable aliases (`ServiceDep = Annotated[...]`); override via `app.dependency_overrides` or factory args. Pure ASGI middleware (state in locals, skip non-http scopes).
- **Patterns:** return annotation alone defines the response model (Pydantic serializes straight to JSON bytes). Custom `RequestValidationError` handlers return `loc/msg/type` only. Examples via `json_schema_extra`/`Field(examples=...)`, named ones via `Body(openapi_examples=...)`. Lifespan may `yield {"key": obj}` → `request.state.key`. Tests: `TestClient` in a `with` block (runs the lifespan; built on httpx2).
- **New and useful:** `Depends(..., scope="function"|"request")`; native SSE (`fastapi.sse.EventSourceResponse`); `strict_content_type=True` by default (bodies without `Content-Type: application/json` are not parsed as JSON).
- **Avoid:** `on_event`/`on_startup` (removed in Starlette 1.0), `BaseHTTPMiddleware` (breaks contextvars), `ORJSONResponse`/`UJSONResponse` (deprecated, unnecessary), redundant `response_model=` next to the same return annotation, `Request[State]` as a FastAPI parameter (fails in 0.141.1).
- **Sources:** Context7 `/websites/fastapi_tiangolo`, `/kludex/starlette` (2026-09-23); installed `routing.py`, `responses.py`, `param_functions.py`, `sse.py`, `starlette/requests.py`, scratch-app checks.

## Pydantic 2.13.5 + pydantic-settings 2.15.0
- **Use:** `Annotated[...]` constraints; `AfterValidator` for single-field rules (no JSON-schema keywords, errors at the field's `loc`); `@model_validator(mode="after")` → `Self` only for cross-field rules. `BaseSettings` + `SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")`, `SecretStr`, fail-fast validators, `@lru_cache get_settings()`.
- **Patterns:** `model_json_schema(mode=...)` per purpose; `TypeAdapter` for non-models. Settings precedence init → env → dotenv → secrets → defaults (`settings_customise_sources` to change); tests use `Settings(_env_file=None, ...)`.
- **New and useful:** `Field(exclude_if=...)`, `validate_by_name`/`validate_by_alias`/`serialize_by_alias`, `polymorphic_serialization`. pydantic-settings `CliApp.run(Model)` / `cli_parse_args` turn a settings model into a CLI.
- **Avoid:** `@validator`/`@root_validator`/`class Config`; `Sequence`/`Mapping` where `list`/`dict` fit (slower); `BaseSettings` from `pydantic`; `settings_cached()` (in docs, absent in 2.15.0).
- **Sources:** Context7 `/pydantic/pydantic` (main ≈ 2.14b), `/pydantic/pydantic-settings` (2026-09-23); installed `Field`/`ConfigDict` signatures, `hasattr` checks.

## Uvicorn 0.53.0
- **Use:** dev `uvicorn app.main:app --reload`; prod `uvicorn app.main:create_app --factory --workers N --forwarded-allow-ips <proxy CIDR> --timeout-graceful-shutdown 30`.
- **Patterns:** `--workers` (or `$WEB_CONCURRENCY`) is incompatible with `--reload`; `--limit-concurrency`, `--limit-max-requests` (+ jitter) for backpressure and recycling.
- **Avoid:** `uvicorn.workers` (deprecated → `uvicorn-worker`), `--forwarded-allow-ips '*'` unless only the proxy can reach the app.
- **Sources:** Context7 `/kludex/uvicorn` (2026-09-23); `uvicorn --help`, `Config.__init__`.

## httpx2 2.13.0
- **Use:** the HTTP stack of openai 3.x, anthropic 1.x, and Starlette's `TestClient` (fork of httpx 0.28 with the same API). Mock with `httpx2.MockTransport` passed via `http_client=`.
- **Avoid:** mixing `httpx` and `httpx2` objects (separate class hierarchies; anthropic rejects httpx objects).
- **Sources:** Context7 `/pydantic/httpx2` (2026-09-23); SDK METADATA requirements.

## Tooling: uv, pytest 9.1.1, pytest-asyncio 1.4.0, ruff 0.16.8, mypy 2.3.1
- **uv:** here pinned `[tool.uv] required-version = ">=0.12.18,<0.13"`, local 0.12.18. `.python-version` + committed `uv.lock`; CI `uv sync --locked` (+ `UV_LOCKED=1` so later `uv run` never re-locks); upgrade with `uv lock --upgrade[-package X]`. Pin the tool with `[tool.uv] required-version` (setup-uv reads it). Latest is 0.12.x; minor bumps are breaking.
- **pytest 9:** native `[tool.pytest]` table with `strict = true` (strict config/markers/xfail/ids); built-in `subtests`, `RaisesGroup`. Deprecated: generator `argvalues`, `--pastebin`.
- **pytest-asyncio 1.x:** reads the native `[tool.pytest]` table (verified 1.4.0). Starlette 1.6.0's `TestClient` emits an `anyio.abc.BlockingPortal` DeprecationWarning (upstream). `asyncio_mode = "auto"`; set `asyncio_default_fixture_loop_scope` explicitly; `event_loop` fixture is gone; use `loop_scope=`.
- **ruff 0.16:** default set is now 413 rules — use `extend-select` (plain `select` replaces the defaults); `# ruff: ignore[CODE]`; `--output-format github` in CI; formatter also formats Python blocks in Markdown (exclude doc trees if unwanted).
- **mypy 2.x:** strict + `pydantic.mypy`; `--local-partial-types`/`--strict-bytes` now default; extras worth enabling: `warn_unreachable`, `ignore-without-code`, `redundant-expr`, `truthy-bool`, `possibly-undefined`, `[tool.pydantic-mypy]` flags; `-n N` parallel (experimental).
- **Sources:** Context7 `/websites/astral_sh_uv`, `/pytest-dev/pytest`, `/pytest-dev/pytest-asyncio`, `/websites/astral_sh_ruff`, `/python/mypy` (2026-09-23); `--help` output, release notes, scratch-config runs.

## GitHub Actions: checkout v7.0.1, setup-uv v10.2.0, setup-node v7.0.0
- **Use:** pin full commit SHAs with a version comment (setup-uv publishes no floating major tags); let Dependabot/Renovate bump them.
- **New and useful:** setup-uv reads `version`/`version-file`/`required-version`; `enable-cache` keys on `uv.lock`+`pyproject.toml`; v10 disables caching on `pull_request_target`/`workflow_run`/`release` and adds `version: "latest-known"`.
- **Sources:** Context7 `/astral-sh/setup-uv` (docs at v10.1); `gh release view`, `gh api .../git/ref/tags/*`.

## Findings for this project
All nine findings from 2026-09-23 were resolved by the OpenSpec change `harden-stack-usage` (branch `feat/harden-stack-usage`): OpenAI `prompt_cache_key` + `cache_write_tokens` reporting; Anthropic context-window stop = invalid output; `httpx2`/`pydantic`/`starlette` declared as direct runtime deps (httpx2 was already transitive via both SDKs); uv pinned + `UV_LOCKED=1` in CI; native strict pytest table; ruff `extend-select`; mypy extras; per-model effort levels; schema/API polish. No open findings.
