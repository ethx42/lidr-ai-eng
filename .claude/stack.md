# Tech stack brief

stack-fingerprint: f152647aca7d
updated: 2026-10-07

How the installed versions are meant to be used today. Read before writing code against them; update when you learn something new (`stack-grounding` skill). Installed versions win over memory and over docs for other versions.

## OpenAI Python 3.19.0
- **Use:** `await client.responses.parse(model, instructions=system, input=user, text_format=Model, store=False, ...)` → `output_parsed`. `status == "incomplete"` or `output_parsed is None` = invalid output; schema-invalid JSON raises `pydantic.ValidationError` inside `parse`. Never mix `text_format` with `text={"format": ...}`.
- **Patterns:** truncated or refused output makes `parse` raise `ValidationError` (`json_invalid`) before `status` is visible; to name the stop condition, call `responses.with_raw_response.parse(...)`, read `http_response.json()["status"/"incomplete_details"]`, then `.parse()` (lazy; verified 3.19.0). Client-level `timeout`/`max_retries` (defaults 10 min / 2); per call `client.with_options(...)`. Catch `APIConnectionError` (incl. timeout) → `RateLimitError` → `APIStatusError`. SDK obeys `x-should-retry`; there is no middleware, so an httpx2 response hook is the place to stop retries on `insufficient_quota` 429s. Close with `await client.close()`.
- **Reasoning:** `reasoning={"effort": ...}` accepts `none|minimal|low|medium|high|xhigh|max` in the SDK, but models reject unsupported levels with 400. Live probe (2026-09-23): gpt-5/-mini/-nano `minimal..high`; gpt-5.1 `none,low..high`; gpt-5.2–5.5 add `xhigh`; gpt-5.6-* add `max`; o3/o4-mini `low..high`. `verbosity` is a top-level param.
- **New and useful:** `prompt_cache_key` groups requests sharing a prefix (≈15 req/min per key). Measured here: gpt-4o-mini went from 0 to 6016 of ~6400 input tokens cached on calls 2–5 once the key was set. `usage.input_tokens_details.cache_write_tokens` exists, but gpt-4o-mini reports 0 even on the first (writing) call. gpt-5.6+: `prompt_cache_options={mode, ttl, prewarm}` with explicit breakpoints; `responses.input_tokens.count(...)`.
- **Avoid:** `prompt_cache_retention` (deprecated → `prompt_cache_options.ttl`); `output_text` for structured results; `user=` (use `prompt_cache_key`/`safety_identifier`); Chat Completions `.parse` for new code.
- **Sources:** Context7 `/openai/openai-python` (lists ≤v2.11 but README is 3.x) + `/websites/developers_openai_api` (2026-09-23); installed signatures, `types/responses/*`, `_base_client.py` `_should_retry`.

## Anthropic Python 1.8.0
- **Use:** `await client.messages.parse(model, max_tokens, system=[{type:"text", text, cache_control:{type:"ephemeral"}}], messages=[...], output_format=Model)` → `parsed_output`. `output_format` takes a class only; raw schemas go in `output_config={"format": ...}`; `output_config={"effort": ...}` merges with it (`low|medium|high|xhigh|max`).
- **Patterns:** `parse()` = `create(output_config={"format": {"type": "json_schema", "schema": transform_schema(TypeAdapter(T).json_schema())}})` + `validate_json`; on cut-off JSON it raises `ValidationError` before `stop_reason` is readable, and there is no `with_raw_response.parse`. To name the stop condition, call `create` with that format (`anthropic.transform_schema` is public), check `stop_reason`, then validate (this project; a wire test pins the format to `parse()`'s). Effort levels `low|medium|high|xhigh|max` all accepted by claude-sonnet-5, opus-5(-5), fable-5(-1) (live probe 2026-09-23). `stop_reason` includes `model_context_window_exceeded` (treat as truncation). thinking: `{"type":"adaptive"}` on newer models, `{"type":"enabled","budget_tokens":N}` on `claude-haiku-4-5`; `max_tokens` must cover thinking. Retries 408/409/429/5xx/connection with backoff; honours `retry-after(-ms)` and `x-should-retry`. `usage.input_tokens` excludes cache: total = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
- **New and useful:** `AsyncAnthropic(middleware=[...])` runs once per attempt inside the retry loop (cleaner than httpx hooks). `cache_control` `ttl: "5m"|"1h"`. `count_tokens(..., output_format=Model)`. Beta `diagnostics={"previous_message_id": ...}` returns `cache_miss_reason`. `Message.stop_details` for structured refusals.
- **Avoid:** running the `anthropic` logger at DEBUG in the app: `_base_client` logs `Request options` with the full request body (verified 1.8.0; openai 3.19.0 does not). `temperature`/`top_p`/`top_k` kwargs (removed → `TypeError`; older models such as Haiku 4.5 still honour them via `extra_body`). `parse(stream=True)` (use `messages.stream(output_format=...)`). Top-level `cache_control` is not accepted by `parse()`; keep the block-level marker.
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
All nine findings from 2026-09-23 were resolved by the OpenSpec change `harden-stack-usage` (archived on `feat/m1-cag-estimator`): OpenAI `prompt_cache_key` + `cache_write_tokens` reporting; Anthropic context-window stop = invalid output; `httpx2`/`pydantic`/`starlette` declared as direct runtime deps (httpx2 was already transitive via both SDKs); uv pinned + `UV_LOCKED=1` in CI; native strict pytest table; ruff `extend-select`; mypy extras; per-model effort levels; schema/API polish.

The M1 review (2026-09-23) found the Anthropic SDK logging request bodies at the default `LOG_LEVEL=DEBUG` and failures logged without a cause; both were resolved by `harden-observability` (client loggers capped at INFO; stop condition read before parsing). No open findings.

---

# Catch-up additions (2026-10-06): streaming, cache, prompts, uploads

Verified for `docs/catch-up/plan-session-0N.md`. Where this section and an older one disagree, this one wins.

checked: 2026-10-06 · project `.venv` (openai 3.19.0, anthropic 1.8.0, fastapi 0.141.1, starlette 1.6.0, httpx2/httpcore2 2.13.0, anyio 4.15.1, uvicorn 0.53.0, jiter 0.17.0, pydantic-core 2.46.5)

Method: Context7 docs plus the installed source and signatures. Every behaviour marked "verified" was reproduced with a scratch script: mock SSE through `httpx2.MockTransport`, uvicorn in-process, or a real network round trip. Packages not yet installed were checked at their latest PyPI version with `uv run --no-project --with ...`. Anything not reproduced is marked *(unverified)*.

### OpenAI Python 3.19.0: Responses streaming
- **Use:**
  ```python
  async with client.responses.stream(model=m, instructions=system, input=user, store=False,
                                     prompt_cache_key=key, text={"format": FORMAT},
                                     stream_options={"include_obfuscation": False}, **params) as stream:
      async for ev in stream:
          match ev.type:
              case "response.output_text.delta": ev.delta, ev.snapshot   # snapshot = accumulated text (str)
              case "response.refusal.delta": ...                         # refusal text
              case "response.completed" | "response.incomplete" | "response.failed": terminal = ev.response
              case "error": ev.code, ev.message                          # flat ResponseErrorEvent
  # status == "completed" -> schema.model_validate_json(terminal.output_text)
  ```
  - `FORMAT = type_to_text_format_param(schema)` from `openai.lib._parsing._responses`. This is the private function that both `parse()` and `stream(text_format=)` call. It builds `{"type": "json_schema", "strict": True, "name": ..., "schema": ...}`.
  - Verified: the wire `text.format` is identical to the one the `text_format=` path sends. Pin it with a wire test, the same way `anthropic_provider.output_format` is pinned to `parse()`.
- **Patterns:**
  - **Where errors surface:**
    - The HTTP request is sent in `__aenter__`, so status errors (401, 429, 5xx after SDK retries) raise there, before any event. The SDK retries only that initial request.
    - Transport failures during iteration raise `APITimeoutError`/`APIConnectionError` and are never retried.
    - The client `timeout` (60 s here) applies per read, as the gap between chunks, not as a total deadline. Use `anyio.fail_after(total)` around the loop if you need a total budget.
  - **Helper events (verified):**
    - Raw events pass through, plus `ResponseTextDeltaEvent.snapshot` (accumulated text of that content part).
    - `ResponseTextDoneEvent.parsed` is set only when `text_format` is given.
    - `response.completed.response` is a `ParsedResponse`.
    - There is **no partial-JSON parsing** in the Responses helper (delta events have no `parsed`). Only the Chat Completions `.stream()` uses jiter partial parsing.
  - **Terminal states (verified with mock SSE):**
    - `response.completed`: `status="completed"`.
    - `response.incomplete`: `status="incomplete"`, `incomplete_details.reason` ∈ `max_output_tokens|content_filter|max_messages|steered`.
    - `response.failed`: `response.error.code/message`.
    - `error`: flat `{code, message, param, sequence_number}`, per the docs. The SDK **yields** it as `ResponseErrorEvent` and does not raise. Only a nested `{"error": {...}}` payload raises a bare `openai.APIError` (not an `APIStatusError`).
    - `get_final_response()` raises `RuntimeError("Didn't receive a response.completed event.")` for every non-completed outcome.
  - **Refusal:** emits `response.refusal.delta`/`.done`, the final message part has `type == "refusal"`, and `status == "completed"` (verified). Treat it as `reason="refusal"`, as `generate()` does.
  - **Usage:** read it from the terminal event's `response.usage`: `input_tokens` (includes cached), `input_tokens_details.cached_tokens`/`cache_write_tokens`, `output_tokens`, `output_tokens_details.reasoning_tokens`. It is `None` on `response.created`. Whether a live `response.incomplete` carries usage *(unverified live; the schema allows it)*.
  - **Cancellation:**
    - Leaving `async with` (break, exception or `CancelledError`) runs `await response.aclose()`. httpcore2 wraps the close in `AsyncShieldCancellation`, so the upstream TCP connection is closed even inside a cancelled anyio scope.
    - **Verified end-to-end over a real socket:** client disconnect → API generator gets `CancelledError` → the upstream server saw its client hang up within the same millisecond.
- **New and useful:**
  - `stream_options={"include_obfuscation": False}` drops the random `obfuscation` padding on deltas. Only use it on trusted links.
  - `stream.until_done()`.
  - `responses.stream(response_id=..., starting_after=N)` resumes background responses (needs `store=True`, so not for us).
- **Avoid:**
  - `text_format=` in `stream()` for this project. On truncation the helper parses at `response.output_text.done` and raises `pydantic.ValidationError` mid-iteration, before `response.incomplete` arrives (verified). It is the same trap as `parse()`.
  - Relying on `get_final_response()` as the only terminal handling.
  - Treating the `error` event as an exception.
  - Mixing `text_format` with `text={"format": ...}` (`TypeError`).
  - `AsyncResponseStream` exposes only `close/get_final_response/until_done`. There is no public `.response` or request id, unlike Anthropic's.
- **Sources:** Context7 `/openai/openai-python` (helpers.md, `examples/responses/streaming.py`) and `/websites/developers_openai_api` (streaming events `error`, create-stream event sequence), 2026-10-06. Installed `lib/streaming/responses/_responses.py`, `_events.py`, `_streaming.py`, `lib/_parsing/_responses.py`, `types/responses/{response_error_event,response_incomplete_event,response_usage,response}.py`, `response_create_params.StreamOptions`, `httpcore2/_async/connection_pool.py`. Scratch runs: `oai_stream.py`, `oai_pattern.py`, `sse_chain.py`.

### Anthropic Python 1.8.0: Messages streaming
- **Use:**
  ```python
  async with client.messages.stream(model=m, max_tokens=n,
          system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
          messages=[{"role": "user", "content": user}],
          output_config={**effort_cfg, "format": output_format(schema)}, **extra) as stream:
      async for ev in stream:
          if ev.type == "text": ev.text, ev.snapshot, ev.parsed_snapshot()
      message = await stream.get_final_message()
  # message.stop_reason in INVALID_STOP_REASONS -> InvalidModelOutput; else schema.model_validate_json(text)
  ```
  Reuse the existing `output_format()` helper. Verified: `stream(output_format=Model, output_config={"effort": ...})` sends an `output_config` identical to `{"effort": ..., "format": output_format(Model)}`.
- **Patterns:**
  - **Events:**
    - `message_start`: usage `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`.
    - `content_block_start`.
    - `content_block_delta`, plus the SDK's `TextEvent` (`type="text"`, `text`, `snapshot`, `parsed_snapshot()`).
    - `content_block_stop`: the SDK adds `content_block`, with `parsed_output` only when `output_format` is given.
    - `message_delta`: `delta.stop_reason`, `delta.stop_details`, and `usage.output_tokens` as a cumulative total that overwrites.
    - `message_stop`: the SDK adds the `message` snapshot.
    - The SDK swallows `ping`.
  - **`get_final_message()`** returns the snapshot for **any** stop reason. Unlike OpenAI there is no RuntimeError (verified for `max_tokens`). `stop_reason` is only known after `message_delta`. Usage is merged across events, so `input_tokens` still excludes cache (total = input + cache_read + cache_creation).
  - **`parsed_snapshot()`** is `jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")` returning a dict. It raises `ValueError` on an empty or whitespace snapshot, so guard it. Verified: `{"title": "App", "hou` gives `{'title': 'App'}`.
  - **Errors:**
    - The first HTTP failure raises in `__aenter__`, after SDK retries on 408/409/429/5xx/529.
    - A mid-stream `event: error` (for example `overloaded_error`) raises `anthropic.APIStatusError` with **`status_code == 200`** and `body={"type":"error","error":{"type":"overloaded_error",...}}`. It is never retried (verified).
    - The current `map_error` sends that through `from_status(200)`, which becomes the generic `UpstreamError`. Classify by `exc.body["error"]["type"]` instead: `overloaded_error`/`api_error` → unavailable, `rate_limit_error` → rate limited.
    - Transport errors mid-stream raise `APIConnectionError`/`APITimeoutError`.
  - **Cancellation:** leaving `async with` runs `close()` → `response.aclose()`. This is the same httpx2/httpcore2 shielded close as OpenAI. It was verified end-to-end for OpenAI; Anthropic shares the code path but was not run separately. `stream.response` and `stream.request_id` are public, so log the request id.
  - **Caching:** a block-level `cache_control` on the system block works in `stream()`. A top-level `cache_control` (it marks the last cacheable block) is accepted by `create`/`stream`/`count_tokens` but **not** by `parse` (verified by signature). Keep the block-level marker for one code path. `ttl: "5m"|"1h"`.
  - **Refusal:** `stop_reason == "refusal"`, plus `message.stop_details` (`RefusalStopDetails`: `category`, `explanation`). `StopReason` = `end_turn|max_tokens|stop_sequence|tool_use|pause_turn|refusal|model_context_window_exceeded`.
- **New and useful:** `stream.text_stream` (text deltas only), `current_message_snapshot`, `get_final_text()`, `until_done()`.
- **Avoid:**
  - `output_format=Model` on the stream for this project. `content_block_stop` validates and raises `ValidationError` before `message_delta.stop_reason` arrives (verified).
  - A schema dict in `output_format` (`TypeError`; it belongs in `output_config`).
  - `messages.parse(stream=True)`.
  - The `temperature` kwarg (keep `extra_body`).
- **Sources:** Context7 `/anthropics/anthropic-sdk-python` (MIGRATION.md "parse streaming → stream", `examples/structured_outputs_streaming.py`, the `_streaming.py` mid-stream error handler, `message_create_params` top-level `cache_control`), 2026-10-06. Installed `lib/streaming/_messages.py`, `lib/streaming/_types.py`, `_streaming.py`, `resources/messages/messages.py` (`stream`), `types/stop_reason.py`, `types/refusal_stop_details.py`. Scratch runs: `ant_stream.py`, `misc.py`.

### jiter 0.17.0 (partial JSON)
- **Use:** `jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")` on the accumulated snapshot. Input must be `bytes`; `str` raises `TypeError` (verified).
  - **Direct dependency** (`jiter>=0.17.0`, added 2026-10-07 by Task 3; `app/services/streaming.py`). openai 3.19.0 (`jiter>=0.16.0,<1`) and anthropic 1.8.0 (`jiter>=0.4.0,<1`) also pull it in (both METADATA). It is MIT-licensed, released 2026-09-12, and is the latest version.
- **Patterns (verified probe):**

  | Input tail | `True`/`"on"` | `"trailing-strings"` |
  |---|---|---|
  | `{"title": "Ap` | `{}` (partial string and its key dropped) | `{'title': 'Ap'}` |
  | `["x", "y` | `['x']` | `['x', 'y']` |
  | `"A\u00` (partial escape) | `{}` | `'A'` (escape dropped) |
  | `{"ti`, `{"title"`, `{"title":` | `{}` | `{}` |
  | `{"hours": 1` | `{'hours': 1}` | same, **although it may become 12** |
  | `12.`, `-`, `1e`, `tr`, `nul` | dropped | dropped |
  | `[{"a": 1}, {"a": 2` | partial objects included | same |
  | `''` / whitespace | `ValueError` | `ValueError` |
  | `{"a": 1} x` | `{'a': 1}` (trailing garbage ignored) | same (`partial_mode=False` raises "trailing characters") |
  | `garbage {`, `\x00`, `[` × 5000 (recursion limit), `"\ud800"` (lone surrogate escape) | `ValueError` | `ValueError` |
  | `{"a": 1e999`, `{"a": NaN` | `inf`, `nan` (`allow_inf_nan=True` default) | same |

  - Every failure seen is a `ValueError`, and `str.encode()` of a lone surrogate raises `UnicodeEncodeError` (a `ValueError` subclass), so one `except ValueError` around `from_json(s.encode(), ...)` covers malformed partials (verified 2026-10-07).
  - Send partials as plain dicts. Validate only the final text with the strict model.
  - Pydantic's `TypeAdapter.validate_json(..., experimental_allow_partial="trailing-strings")` raises for a `BaseModel` with required fields. It only helps for `list[Model]` (it drops the incomplete last item) or a `TypedDict` with `NotRequired` fields (verified).
- **Performance (measured):** re-parsing the whole 10 KB snapshot on each of 2,500 deltas took 4 µs per delta, 10 ms in total. A full parse is about 2x faster than `json.loads`. That is O(n²) but negligible at LLM output sizes. Throttle SSE emits for bandwidth (emit only when the dict changed, or every N ms), not for CPU.
- **New and useful:** `pydantic_core.from_json(data, allow_partial="trailing-strings")` is the same engine and accepts `str` or `bytes`. It is a fallback if you would rather not add the dependency.
- **Avoid:** showing a trailing number as final, since it may still grow (only values before the last token are stable). Also avoid `partial_mode=True` when partial string values should be shown live.
- **Sources:** Context7 has no jiter entry (`/pydantic/jiter` not found; the name search returned only unrelated libraries), so this section relies on the installed `jiter/__init__.pyi`, `anthropic/lib/streaming/_types.py` (`parsed_snapshot`), SDK METADATA, PyPI JSON, and the scratch scripts `jiter_probe.py` and `pc_partial.py` (2026-10-06).

### FastAPI 0.141.1 + Starlette 1.6.0: native SSE
- **Use:**
  ```python
  @router.post("/estimations/stream", response_class=EventSourceResponse,
               dependencies=[Depends(preflight)])            # 4xx-capable checks here
  async def stream(body: EstimateRequest, svc: ServiceDep) -> AsyncIterator[ServerSentEvent]:
      yield ServerSentEvent(event="partial", data=partial_dict, id=str(seq))
      yield ServerSentEvent(event="result", data=result_model)
  ```
  A Pydantic body is validated before streaming and returns the normal 422 JSON (verified).
- **Patterns:**
  - **Encoding (verified):**
    - `data=` is always JSON. A model goes through `model_dump_json()` (compact). A dict goes through `json.dumps(jsonable_encoder(x))` (`{"a": 1}`, with spaces). Strings get quoted.
    - `raw_data=` is sent verbatim, and newlines become multiple `data:` lines.
    - `event`/`id` must be a single line (`id` with no NUL). `retry` is in milliseconds. `comment` is sent as `: text`.
    - With `-> AsyncIterable[Model]`, plain yielded items are validated and sent as bare `data:` lines.
  - **Headers:** FastAPI sets `text/event-stream; charset=utf-8`, `Cache-Control: no-cache` and `X-Accel-Buffering: no` itself (verified). Extra headers must be set from a **dependency** via `response: Response` (verified). Setting them inside the generator body is ignored (verified).
  - **Keep-alive:** sends `: ping\n\n` after 15 s idle (`_PING_INTERVAL`). It is imported by name into `fastapi.routing`, so tests patch `monkeypatch.setattr(fastapi.routing, "_PING_INTERVAL", 0.1)` (verified). It cannot be configured per route.
  - **Mechanics:**
    - The generator runs in a producer task (anyio task group plus a memory stream, buffer 1) entered on the request-scoped exit stack.
    - Starlette runs `listen_for_disconnect` because uvicorn 0.53 advertises ASGI `spec_version` "2.3". At ≥2.4 a disconnect would only be noticed on a failed `send`.
  - **Client disconnect (verified with uvicorn):**
    - It is detected immediately. The generator gets **`CancelledError`** at its current `await` (not `GeneratorExit`), then `finally` runs.
    - Any further `await` in cleanup raises `CancelledError` again (anyio cancellation is level-triggered). Cleanup that must await (usage logging, Redis write) needs `with anyio.CancelScope(shield=True), anyio.move_on_after(1): ...`.
    - Always re-raise. An `async with client.*.stream(...)` inside the generator closes the upstream by itself.
    - If cancellation lands while the generator is parked at `yield` (producer blocked on the full buffer), it is finalized later by the loop's async-generator hook *(from source, unverified)*.
  - **Errors after headers:**
    - Anything raised inside the generator, even `HTTPException` before the first `yield`, ends as **200 with an empty or truncated body**: `/early` returned `200 ''` (verified).
    - Uncaught exceptions surface as `ExceptionGroup`, which TestClient re-raises. Exception handlers don't apply.
    - Rule: put 4xx checks (size, auth, extraction, rate limit) in dependencies (`/dep` returned a proper 413 JSON, verified). Inside the generator, catch errors and `yield ServerSentEvent(event="error", data={"code": ..., "message": ...})`, then return.
  - **Testing:**
    - `TestClient` and `httpx2.ASGITransport` both buffer the **whole** response (`BytesIO`/`b"".join`), so `client.stream()` gets everything at the end. Streams under test must terminate, or the test hangs. Neither can simulate a mid-stream disconnect.
    - To test disconnect, unit-test the generator (`aclose()` or cancel the task), or run uvicorn in-process (`uvicorn.Server(Config(app, port=...)).serve()` as a task) with an `httpx2.AsyncClient` stream.
    - Parse SSE in tests by splitting `r.text` on `"\n\n"`.
- **New and useful:** `ServerSentEvent(comment=...)`. SSE works on any method (POST is fine). `format_sse_event(...)` is public, for hand-built streams.
- **Avoid:**
  - `sse-starlette` (redundant now).
  - A plain `StreamingResponse` for SSE (no pings and no anti-buffering headers).
  - Raising `HTTPException` in the generator.
  - Swallowing `CancelledError`.
  - Unshielded awaits in `finally`.
  - Patching `fastapi.sse._PING_INTERVAL` (has no effect).
- **Sources:** Context7 `/websites/fastapi_tiangolo` (tutorial/server-sent-events, reference/sse), 2026-10-06. Installed `fastapi/sse.py`, `fastapi/routing.py` (around lines 520–640), `starlette/responses.py` (`StreamingResponse.__call__`), `starlette/testclient.py`, `uvicorn/protocols/http/*_impl.py` (`spec_version`). Scratch runs: `sse_disconnect.py`, `sse_chain.py`, `sse_testclient.py`, `sse_early.py`, `misc.py`.

### FastAPI 0.141.1 multipart + python-multipart 0.0.32
- **Use:**
  - Add `python-multipart>=0.0.32` as a direct dependency. It is the latest (2026-06-04, Apache-2.0) and is **not installed** today. Without it, FastAPI raises `RuntimeError` at route registration for any `Form`/`File` param. Don't use `fastapi[standard]` just for this.
  - Verified shape: a single form model that also holds the files.
  ```python
  class EstimateForm(BaseModel):
      model_config = {"extra": "forbid"}
      title: str = Field(min_length=1)
      mode: Literal["fast", "deep"] = "fast"
      files: list[UploadFile] = []
  async def ep(form: Annotated[EstimateForm, Form()]): ...
  ```
  - Error locs come out clean: `["body","title"]` and `extra_forbidden` at `["body","bogus"]`.
  - `list[str]` accepts repeated keys.
  - `payload: Json[Model]` works for a JSON field inside the form.
- **Patterns:**
  - **`UploadFile`** has `filename`, `size`, `content_type`, `headers`, and the async methods `read(size=-1)`, `write`, `seek(offset)` (no `whence`) and `close()`.
    - `.file` is a `SpooledTemporaryFile` that moves to disk above 1 MB.
    - Run CPU-bound parsers with `await run_in_threadpool(parse, f.file)` or `anyio.to_thread.run_sync`.
    - FastAPI closes form files after the response completes; they are still open inside a streaming generator (verified).
  - **Size limits:**
    - FastAPI calls `request.form()` with Starlette's defaults (`max_files=1000`, `max_fields=1000`, `max_part_size=1 MB`) and offers no knob. `max_part_size` covers **non-file fields only** (over the limit: 400). File parts have no size limit.
    - Cap the total with `starlette.middleware.body_limit.RequestBodyLimitMiddleware(max_body_size=N)`. Verified: it returns 413 `text/plain` "Content Too Large" and catches chunked bodies too.
    - `FastAPI`/`APIRouter`/`APIRoute` do not accept `max_body_size` (Starlette's `Route`/`Mount` do).
    - Enforce per-file count and size after parsing (`len(form.files)`, `f.size`).
- **New and useful:** `RequestBodyLimitMiddleware` (Starlette 1.6). Since Starlette 1.3.1 the field and part limits are actually enforced inside the parser.
- **Avoid:**
  - Mixing `Annotated[Model, Form()]` with any other `Form()`/`File()` param. FastAPI then expects the model embedded under its param name, giving 422 `missing ["body","<param>"]` (verified). Put the files inside the model.
  - `list[bytes]` for large files.
  - A mutable `= []` default on function params (ruff B006); inside the model it is fine.
  - Trusting `max_part_size` for files.
- **Sources:** Context7 `/websites/fastapi_tiangolo` (request-form-models, request-files, request-forms-and-files) and `/kludex/starlette` (requests, formparsers notes), 2026-10-06. Installed `starlette/formparsers.py`, `requests.py`, `datastructures.py`, `middleware/body_limit.py`, `fastapi/dependencies/utils.py`, plus PyPI JSON and scratch TestClient runs.

### redis-py 8.1.0 (asyncio) + fakeredis 2.39.0 + Redis image 8.10.2
- **Use:**
  ```python
  r = redis.asyncio.from_url(url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25)
  await r.get(k)
  await r.set(k, v, ex=ttl)
  await r.aclose()   # in the lifespan
  ```
  - `from_url` is a plain function (do not `await` it) and connects lazily: a bad host only fails on the first command.
  - Fail-open: catch `redis.exceptions.RedisError`. It covers `ConnectionError`, `TimeoutError`, `BusyLoadingError`, `AuthenticationError`, `MaxConnectionsError` and `ResponseError`.
  - Verified: a refused port raises `ConnectionError`, a blackholed IP raises `TimeoutError`, and a DNS failure raises `ConnectionError`. All are `RedisError`; none is the builtin.
- **Patterns:**
  - **Retry defaults differ by constructor (measured):**
    - `Redis(host=...)` uses `Retry(ExponentialWithJitterBackoff(0.01, 1), retries=10)`: a refused connection took 4.6 s to fail.
    - `from_url` uses `Retry(NoBackoff(), 0)`: it fails at once.
  - **Timeouts:** the 8.x defaults are `socket_timeout=5` and `socket_connect_timeout=5`, so lower both for a fail-open cache.
  - **mypy:** `await r.get()` is typed `bytes | str | None` even with `decode_responses=True`, so narrow with `isinstance(v, str)`.
  - **fakeredis:**
    - `fakeredis.FakeAsyncRedis(decode_responses=True)` subclasses `redis.asyncio.Redis`, so it is a drop-in through factory args or `dependency_overrides`.
    - Simulate an outage with `server = fakeredis.FakeServer(); r = FakeAsyncRedis(server=server); server.connected = False`, or with `FakeAsyncRedis(connected=False)`. Either raises `redis.exceptions.ConnectionError` (verified).
    - No `lupa` is needed unless you use Lua.
- **New and useful:**
  - 8.0 (2026-05-28) speaks RESP3 on the wire by default, while `legacy_responses=True` keeps the RESP2 result shapes (GET/SET are unaffected). It also turned on TCP keepalive by default.
  - `set(ifeq=..., ifne=...)`.
  - 8.1 added async maintenance notifications.
- **Docker:**
  - `redis:8` = `redis:latest` = `8.10.2` (Debian trixie). `redis:8-alpine` = `8.10.2-alpine`. Pin `redis:8.10-alpine` or `redis:8-alpine`.
  - Redis ≥8.0 is tri-licensed RSALv2/SSPLv1/AGPLv3. Using the server unmodified as a cache does not touch our code *(usual reading, not legal advice)*.
  - BSD alternative: `valkey/valkey:9.0-alpine` (same client; fakeredis supports it).
- **Avoid:**
  - `close()` (deprecated → `aclose()`).
  - `retry_on_timeout=` (deprecated).
  - `lib_name`/`lib_version` (use `driver_info`).
  - A bare `except ConnectionError`/`TimeoutError`, which catches the builtins.
  - `Redis(host=...)` on the fail-open path.
  - Sharing a `FakeAsyncRedis.from_url(same_url)` across tests (they share state; use a fresh `FakeServer()` per test).
- **Sources:** Context7 `/redis/redis-py` (asyncio, from_url, exceptions, retry) and `/cunla/fakeredis-py` (FakeAsyncRedis, `server.connected`), 2026-10-06. PyPI JSON (redis 8.1.0 MIT, fakeredis 2.39.0 from 2026-10-01), installed signatures in a scratch env, timing and exception probes, GitHub release notes 8.0.0/8.1.0, and the Docker Hub tags API with digest comparison.

### Jinja2 3.1.6 (MarkupSafe 3.0.4)
- **Use:**
  ```python
  Environment(loader=FileSystemLoader(dir), undefined=StrictUndefined, trim_blocks=True,
              lstrip_blocks=True, keep_trailing_newline=True, auto_reload=False,
              autoescape=False)  # noqa: S701 (plain-text LLM prompts, never HTML)
  ```
  - Build it once (module level or lifespan), then call `env.get_template(name).render(**ctx)`.
  - 3.1.6 (2025-03-05) is still the latest.
  - Verified defaults: `cache_size=400`, `auto_reload=True`, `optimized=True`, and the whitespace flags off.
- **Patterns:**
  - **`StrictUndefined` (verified):** raises `UndefinedError` on output of a missing variable, `{% if missing %}`, `{% for x in missing %}` and `d.missing_key`. It allows `is defined` and `| default(...)`. `maybe.attr | default` still raises when `maybe` itself is undefined.
  - **Include:** `{% include "x.j2" %}` passes the full context, including loop variables. `without context` hides it, `ignore missing` renders nothing, and a list picks the first template that exists.
  - **Caching:** `get_template` returns the cached object, keyed by loader and name. `auto_reload=True` stats the file on every hit.
  - **Errors:** `TemplateNotFound` is an `OSError`, a `LookupError` and a `TemplateError`. `TemplateSyntaxError` is raised at load, `UndefinedError` at render. Load all templates at startup so they fail fast.
- **New and useful:** `trim_blocks` + `lstrip_blocks` remove the stray blank lines around tags (verified). `select_template([...])`.
- **Avoid:**
  - The default `Undefined`, which silently renders empty strings into prompts.
  - `from_string(user_text)`.
  - Autoescaping for prompts (it would HTML-escape user input).
  - `select_autoescape(default=False)` as a lint dodge (it still escapes `from_string` templates).
  - `ImmutableSandboxedEnvironment` and `enable_async` (not needed: the templates are trusted and rendering is CPU-only).
- **Sources:** Context7 `/websites/jinja_palletsprojects_en_stable` (Environment options, include, select_autoescape) and `/pallets/jinja` (template cache), 2026-10-06. PyPI, the installed signature in a scratch env, probe templates, and a ruff 0.16.8 `--select S` run.

### pypdf 6.19.0
- **Use:**
  - Depend on `pypdf[crypto]>=6.19.0` (latest, 2026-09-16, BSD-3-Clause, `py.typed`). The extra pulls in `cryptography`.
  - `reader = PdfReader(io.BytesIO(data))` (signature `PdfReader(stream, strict=False, password=None, *, root_object_recovery_limit=10000)`). Check `len(reader.pages)` against the cap first (cheap), then `page.extract_text()` (`extraction_mode="plain"` is the default; keep it).
  - Run it in a thread: about 3.8 ms per page of plain extraction; 300 pages open and count in 14 ms.
- **Patterns:**
  - **Encryption (verified on RC4-128, AES-128 and AES-256):**
    - Owner-password-only PDFs read without `decrypt` (pypdf tries the empty user password).
    - With a user password, `decrypt("")` or a wrong password returns `PasswordType.NOT_DECRYPTED` (0) and does not raise. Page access then raises `FileNotDecryptedError`.
    - `PdfReader(..., password="wrong")` raises `WrongPasswordError`.
    - Without `cryptography`, **any** AES PDF raises `DependencyError`, even owner-only ones.
  - **Errors:**
    - Catch `(pypdf.errors.PyPdfError, pypdf.errors.DependencyError)`. `DependencyError` is not a `PyPdfError`.
    - The `PyPdfError` hierarchy includes `PdfReadError` (with `PdfStreamError`, `EmptyFileError` and `FileNotDecryptedError`, which in turn has `WrongPasswordError`), `ParseError` and `LimitReachedError`.
    - Observed: `b""` raises `EmptyFileError`; garbage or truncated input raises `PdfStreamError`.
  - A scanned or blank page returns `""` (no OCR). Treat "every page empty" as unsupported content.
  - Malformed files log WARNINGs on the `pypdf._reader` logger; cap that logger.
- **New and useful:** resource limits via `pypdf.Configuration` (6.18), applied with `with pypdf.apply_configuration(zlib_maximum_output_length=..., page_tree_maximum_entries=...)` (ContextVar-based; it propagates into `asyncio.to_thread`, verified). The defaults are a 75 MB decompressed stream and 100k page-tree entries. Exceeding a limit raises `LimitReachedError`. 6.14–6.19 are mostly security fixes, so keep the floor current.
- **Avoid:** mutating `pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH` and similar constants (deprecated, removed in 7.0); `strict=True` for uploads; `extraction_mode="layout"` (experimental); relying on the text order.
- **Sources:** Context7 `/websites/pypdf_readthedocs_io_en_stable` (extract_text, encryption, errors) and `/py-pdf/pypdf` (Configuration, changelog), 2026-10-06. PyPI JSON, `inspect.signature` and the `pypdf.errors` MRO on 6.19.0, and reportlab-generated plain and encrypted PDFs.

### python-docx 1.2.0 + licenses
- **Use:**
  - Depend on `python-docx>=1.2.0` (latest, 2025-06-16, MIT; deps `lxml` (BSD-3) and `typing_extensions`; `py.typed`).
  - `doc = Document(io.BytesIO(data))`.
  - `doc.iter_inner_content()` yields `Paragraph | Table` in document order (verified). Use it rather than separate `doc.paragraphs` and `doc.tables` passes.
  - Get headers and footers from `doc.sections[i].header/footer.paragraphs`.
- **Patterns:**
  - **Tables:** walk `table.rows` → `row.cells` → `cell.text`. Nested tables are **not** in `cell.text`; recurse with `cell.tables`/`cell.iter_inner_content()`.
  - **Merged cells repeat:**
    - A horizontal merge yields the same `_Cell` object, so dedupe with `dict.fromkeys(row.cells)`.
    - A vertical merge yields a new `_Cell` over the same `cell._tc`, so dedupe by `id(cell._tc)` (private).
    - Rows may also have fewer cells than the grid.
  - **Errors (verified):**
    - Garbage, empty or legacy `.doc` input raises `zipfile.BadZipFile`.
    - A zip without `[Content_Types].xml` raises `KeyError`.
    - Another OOXML type (xlsx) raises `ValueError("... is not a Word file ...")`.
    - `PackageNotFoundError` is raised only for path strings.
  - XXE is off (`resolve_entities=False`), but there is **no zip-bomb guard**. Check `sum(i.file_size for i in zipfile.ZipFile(buf).infolist()) <= cap`, then `buf.seek(0)`.
  - It is sync, so run it in a thread.
- **Licenses (PyPI metadata, 2026-10-06):**
  - pypdf: BSD-3-Clause.
  - python-docx: MIT.
  - lxml: BSD-3-Clause.
  - cryptography: Apache-2.0 OR BSD-3-Clause.
  - python-multipart: Apache-2.0.
  - redis-py: MIT.
  - jiter: MIT.
  - **PyMuPDF 1.28.2: "GNU AFFERO GPL 3.0 or Artifex Commercial License". AGPL is confirmed, so do not add it.**
- **Sources:** Context7 `/python-openxml/python-docx` (`blkcntnr.iter_inner_content`, `table._Row.cells`, tables docs), 2026-10-06. PyPI JSON, a scratch docx with merges, a nested table, header and footer, and the garbage/empty/zip/xlsx inputs.

### httpx2 2.13.0: async integration tests
- **Use:** `httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")`. The signature is `ASGITransport(app, raise_app_exceptions=True, root_path="", client=("127.0.0.1", 123))`. It does **not** run the lifespan (verified: no startup and no `app.state`). The httpx2 docs call lifespan out of scope.
- **Patterns (all verified):**
  - Wrap it in `async with app.router.lifespan_context(app):`. That runs startup and shutdown and sets `app.state`, but a lifespan that yields a dict does not reach `request.state`. This project uses `app.state`, so that is fine, and it needs no new dependency.
  - Or use `asgi_lifespan.LifespanManager(app)` (2.1.0, MIT, depends only on `sniffio`, works with httpx2) with `ASGITransport(app=manager.app)`. Its last release was 2023-03-28: stable, but unmaintained.
  - Or keep the sync `with TestClient(app)` that the project already uses. **Recommended:** keep `TestClient` and add `lifespan_context` only when a test must be async.
  - `raise_app_exceptions=False` turns app crashes into a 500.
- **Avoid:** expecting incremental streaming from either in-process client. `ASGITransport` yields `b"".join(body_parts)` after the app finishes. `ASGIWebSocketTransport` appears in the docs but is absent in 2.13.0. PyPI has 2.13.1 (not evaluated).
- **Sources:** Context7 `/pydantic/httpx2` (transports, websockets) and `/florimondmanca/asgi-lifespan` (README), 2026-10-06. Installed `httpx2/_transports/asgi.py`, `starlette/testclient.py`, PyPI JSON, and scratch runs.

### Provider pricing (checked 2026-10-06, USD per 1M tokens)
| Model / tier | Input | Cached input (read) | Cache write | Output |
|---|---|---|---|---|
| gpt-4o-mini, Standard | 0.15 | 0.075 | not billed separately | 0.60 |
| gpt-4o-mini, Batch | 0.075 | n/a | n/a | 0.30 |
| claude-haiku-4-5 | 1.00 | 0.10 | 1.25 (5 min TTL) / 2.00 (1 h TTL) | 5.00 |
| claude-haiku-4-5, Batch | 0.50 | multipliers stack | multipliers stack | 2.50 |

- **Cost formulas:**
  - OpenAI `input_tokens` **includes** cached tokens: cost = `(input - cached)·0.15 + cached·0.075 + output·0.60`.
  - Anthropic `input_tokens` **excludes** cache tokens: cost = `input·1.00 + cache_creation·1.25 (or 2.00 at 1 h) + cache_read·0.10 + output·5.00`.
- **Notes:**
  - The OpenAI page also lists a "Fast" tier row for gpt-4o-mini (0.25 / 0.125 / 1.00).
  - `inference_geo` (1.1x) applies only to Claude 4.6 and later; sending it to Haiku 4.5 returns 400.
  - Prices change, so keep them in config with a `checked: 2026-10-06` note.
- **Sources:** https://developers.openai.com/api/docs/pricing (no last-updated date on the page; values read from the embedded price table) and https://platform.claude.com/docs/en/about-claude/pricing (model and batch tables), both fetched 2026-10-06.

### Gotchas for the implementers
1. **Never stream with the SDK's parsing helpers.**
   - OpenAI `stream(text_format=)` and Anthropic `stream(output_format=)` both validate when the text block ends, so truncated JSON raises `ValidationError` mid-iteration, *before* `response.incomplete` / `message_delta.stop_reason` arrives (verified for both).
   - Send the schema raw instead: OpenAI `text={"format": type_to_text_format_param(schema)}`, Anthropic `output_config={"format": output_format(schema)}`. Then read the terminal status/stop_reason and validate the final text yourself, which keeps the current "stop condition before validation" rule.
2. **OpenAI terminal handling is on you.**
   - `get_final_response()` raises `RuntimeError` unless `response.completed` arrived.
   - The `error` SSE event is *yielded*, not raised.
   - `response.failed` carries `response.error`. Handle `completed|incomplete|failed|error` explicitly.
3. **Anthropic mid-stream errors arrive as `APIStatusError(status_code=200)`.** Map them by `exc.body["error"]["type"]`; `from_status(200)` would misreport overload as a generic upstream error.
4. **No partial JSON from OpenAI's Responses helper.** Run `jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")` on `ev.snapshot` for both providers, and declare `jiter>=0.17.0` as a direct dependency (it is only transitive via openai and anthropic today).
   - Guard the empty snapshot (`ValueError`).
   - Treat a trailing number as unstable (`{"hours": 1` → `1`).
   - Validate only the final text with the strict model.
5. **Client disconnect means `CancelledError` inside the generator.**
   - Keep the SDK `async with` inside the generator: it closes the upstream (verified over a real socket).
   - Any cleanup await must be shielded (`anyio.CancelScope(shield=True)`) and bounded, because a second await re-raises.
   - Never swallow `CancelledError`.
6. **Once SSE starts, the status is 200 forever.**
   - Put size, auth, extraction, cache and rate-limit checks in dependencies (they still return 4xx).
   - Inside the generator, catch errors and `yield ServerSentEvent(event="error", data=...)`. An `HTTPException` raised in the generator returns `200 ''` (verified).
7. **Headers for SSE must be set in a dependency** via `response: Response`. The anti-buffering headers are already set by FastAPI.
8. **SSE tests:**
   - TestClient and ASGITransport buffer the whole body, so test streams must end.
   - Patch `fastapi.routing._PING_INTERVAL` (not `fastapi.sse`) to test pings.
   - Disconnect tests need uvicorn in-process or a direct unit test of the generator.
   - Mid-stream exceptions surface as `ExceptionGroup`.
9. **The client timeout is per read, not total.** The 60 s client timeout bounds gaps between chunks. Add `anyio.fail_after(total)` around the stream if a wall-clock budget matters.
10. **Multipart:**
    - Add `python-multipart` before the first `Form`/`File` route; app creation fails without it.
    - Put files *inside* the form model (a separate `File()` param gives 422).
    - Filter empty browser file inputs (`filename == ""`, `size == 0`).
    - Cap the body with `RequestBodyLimitMiddleware` (its 413 is `text/plain`, not the project's JSON error shape).
    - Read and extract the uploads before the stream starts.
11. **Parsers are sync and CPU-bound:** call pypdf and python-docx via `run_in_threadpool`/`anyio.to_thread`.
    - Use `pypdf[crypto]`, and catch `PyPdfError` *and* `DependencyError`.
    - Zip-size-guard `.docx` uploads before opening them.
    - An all-empty `extract_text()` is an unsupported (scanned) PDF.
12. **Redis fail-open:**
    - Use `from_url` (no retries) with timeouts of about 0.25–0.5 s, not the 5 s defaults.
    - Catch `redis.exceptions.RedisError` only (the builtin `ConnectionError` doesn't match).
    - Close with `aclose()`.
    - Narrow `get()` results with `isinstance(v, str)` for mypy.
    - Test with `FakeAsyncRedis(server=FakeServer())` and use `server.connected = False` for outages.
13. **Jinja:**
    - `autoescape=False` trips ruff S701 (`S` is enabled), so add `# noqa: S701` with the reason.
    - Use `StrictUndefined` + `auto_reload=False`, and load every template at startup.
    - Include fragments inherit the full context, so their variables must be present or guarded.
14. **Licensing:** no PyMuPDF (AGPL). Every other dependency is MIT, BSD or Apache. The Redis ≥8 server is AGPL/SSPL/RSAL, but we only run it as a separate container.
15. **Newer releases exist but were not evaluated:** fastapi 0.142.2, starlette 1.7.0, httpx2 2.13.1. Stay on the installed versions unless someone decides to bump.

### FastAPI 0.141.1: extending the OpenAPI contract (2026-10-07, Task 2)
- **Use:** models that are not route models (SSE payloads) enter `components.schemas` by wrapping `app.openapi`: call the default (it caches on `app.openapi_schema` and rebuilds when `router._get_routes_version()` changes), merge `jsonable_encoder(models_json_schema([(M, "serialization"), ...], ref_template="#/components/schemas/{model}")[1]["$defs"], exclude_none=True)` into the returned dict, return it. `app.openapi = fn` needs `# type: ignore[method-assign]` under mypy strict (the documented hook).
- **Contract choice: response fields are "always present, nullable".** The server serializes every field (nulls included), so response-side models with defaulted fields (`Usage`, `CallMetrics`, `StatusEvent`) set `ConfigDict(json_schema_serialization_defaults_required=True)` (`RESPONSE_CONFIG` in `app/schemas/estimation.py`): every field is in `required`, nullable ones are `anyOf [T, null]`. Honoured by FastAPI 0.141.1 without splitting models into `-Input`/`-Output` while a model is used only in responses. Request models keep defaults optional. Pinned by `tests/test_openapi_snapshot.py`.
- **Gotcha:** FastAPI dumps its own document with `exclude_none=True` (`fastapi/openapi/utils.py`), so its schemas never carry `"default": null` and **examples silently lose `None` fields** (a required key disappears from the example). Merged schemas are dumped the same way (one convention); examples use non-null values (a test compares the documented example with `example_response()`). Verified 2026-10-07 with `npx openapi-typescript@7.13.0 contracts/openapi.json`: every response property is non-optional (`ttft_ms: number | null`, `StatusEvent.provider: string | null`, `Usage.input_tokens: number`); the only `?:` property is the request's `output_language`.
- **Sources:** Context7 `/websites/fastapi_tiangolo` (how-to/extending-openapi); installed `fastapi/applications.py` `openapi()`, `fastapi/openapi/utils.py`, `fastapi/_compat/v2.py` (`GenerateJsonSchema` differs from pydantic's only for bytes).

### SSE endpoint in practice (2026-10-07, Task 5)
- **Typing `aclosing`:** `contextlib.aclosing(x)` needs `x` typed with `aclose()`; mypy strict rejects an `AsyncIterator` (`type-var` error, verified mypy 2.3.1). Streams that callers close are typed `AsyncGenerator[T]` (one parameter is fine: typeshed defaults the send type), including the `LLMProvider.stream` protocol and every implementation (an `AsyncIterator`-annotated implementation no longer satisfies the protocol).
- **Contract:** `responses={200: {"content": {"text/event-stream": {"schema": {"oneOf": [refs]}}}}}` is deep-merged with FastAPI's default `itemSchema` (generic `data/event/id/retry`), so both appear. openapi-typescript 7.13.0 turns `schema` into a union for the `text/event-stream` content (verified). A body read by a dependency (`Annotated[EstimateRequest, Depends(checked_request)]`) keeps the request body as a plain `$ref` (not embedded) because it is the only body param.
- **Disconnect, verified live (uvicorn 0.53, replay provider):** `curl --max-time 1` mid-stream → the service logs `outcome=cancelled` at ~1005 ms. Build and log the final response *before* yielding trailing events (final flush, `validating`): a client that leaves there still leaves exactly one `llm_call` record.
- **Testing:** `pytest-asyncio` 1.4.0 ships the `unused_tcp_port` fixture; `uvicorn.Server.started` is a plain flag (polling it trips ruff `ASYNC110`, so the line carries a justified `noqa`).

## Web, BFF, Docker and CI (2026-10-06)

**Pins (latest stable, checked with `npm view` / registries):** next 16.4.0 (published 2026-10-06 18:35Z, so day zero; previous line is 16.3.8) · react/react-dom 19.3.0 · typescript 5.9.3 (keep `^5`; see topic 1) · @types/node 24.19.1 · eslint 9.39.5 (`maintenance` tag; 10.12.0 is `latest`) + eslint-config-next 16.4.0 · tailwindcss / @tailwindcss/turbopack / @tailwindcss/postcss 4.3.3 · shadcn 4.21.3 · radix-ui 1.7.0 · @base-ui/react 1.8.0 · tw-animate-css 1.4.0 · lucide-react 1.52.0 · sonner 2.0.8 · next-themes 0.4.6 · react-hook-form 7.89.0 · zod 4.6.5 · @hookform/resolvers 5.9.1 · react-resizable-panels 4.14.2 · openapi-typescript 7.13.0 · openapi-fetch 0.17.0 · eventsource-parser 4.1.1 · vitest 5.0.3 · vite 8.3.3 · @vitejs/plugin-react 6.1.2 · jsdom 30.1.2 · @testing-library/react 16.3.3 · @testing-library/dom 10.4.2 · @testing-library/jest-dom 7.0.1 · @testing-library/user-event 14.6.7 · @playwright/test 1.63.0 · @axe-core/playwright 4.13.0 (axe-core ~4.13) · server-only 0.0.1 · Node 24.21.0 LTS "Krypton" (26.x is Current, not LTS yet) · pnpm 11.5.0 local (newest 11.x is 11.28.x; pnpm 12.9.1 is `latest`) · corepack 0.36.0 (bundled with Node 24) · uv 0.12.23 (`ghcr.io/astral-sh/uv:0.12.23`) · `python:3.12-slim-trixie` (3.12.15) · `node:24.21.0-slim` · `redis:8.10.2-alpine`.

### Next.js 16.4.0 (create-next-app 16.4.0, React 19.3.0, TypeScript 5.9.3, eslint-config-next 16.4.0)
- **Use (scaffold):** run from the repo root and pass every flag, because `--yes` otherwise reuses *saved preferences* from earlier runs on this machine (verified in the bundle: `t.set("preferences", …)`):
  `pnpm dlx create-next-app@16.4.0 web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --no-react-compiler --no-cache-components --no-agent-feedback --agents-md --yes`
  All `--no-*` flags are honoured through raw-argv checks (verified: `--no-cache-components`, `--no-react-compiler`, `--no-src-dir`, `--no-agents-md`, `--no-eslint`, `--no-tailwind`, `--no-app`, `--no-import-alias`, `--no-linter`). Git init is skipped automatically inside an existing work tree (`tryGitInit` checks `git rev-parse --is-inside-work-tree`). It also runs `pnpm exec next typegen` after install.
- **What 16.4's scaffold writes (verified):** Turbopack is the default bundler. With Tailwind it installs **`@tailwindcss/turbopack`**, adds `turbopack.rules["*.css"] = { loaders: ["@tailwindcss/turbopack"], as: "*.css" }` to `next.config.ts`, and writes **no** `postcss.config.mjs` (`--rspack` switches to `@tailwindcss/postcss`). Dev deps: `typescript ^5`, `@types/node ^20`, `@types/react ^19`, `eslint ^9`, `eslint-config-next 16.4.0`. Scripts: `dev: next dev`, `build: next build`, `start: next start`, `lint: eslint`. With pnpm 11 it writes `pnpm-workspace.yaml` containing `allowBuilds: { sharp: false, unrs-resolver: false }` and sets `"packageManager": "pnpm@<local version>"`. Defaults *you are overriding* above: `cacheComponents: true` (+ `partialPrefetching: true`), `experimental.agentFeedback: true`, `agentsMd: true`.
- **Route handlers (BFF):** `src/app/api/**/route.ts` exporting `GET/POST/...` with Web `Request`/`Response`. They are **not cached** by default (GET has been dynamic since 15), the runtime defaults to `nodejs`, and `runtime = 'edge'` is deprecated. Do **not** export `dynamic`, `revalidate`, `fetchCache` or `runtime`. They are unnecessary, and with Cache Components on they fail the build ("will error"). `RouteContext<'/x/[id]'>` and `LayoutProps<'/'>` are global type helpers generated by `next dev|build|typegen`.
- **SSE proxy (no buffering), verified in `next@16.4.0` source:**
  ```ts
  export async function POST(request: Request) {
    const upstream = await fetch(`${serverEnv().API_BASE_URL}/api/v1/...`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: await request.text(),          // small JSON: buffer, validate, forward
      signal: request.signal,              // browser disconnect aborts the upstream
    })
    if (!upstream.ok || !upstream.body)
      return new Response(await upstream.text(), { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" } })
    return new Response(upstream.body, { headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",   // no-transform makes Next's gzip skip this response
      "x-accel-buffering": "no",
    } })
  }
  ```
  Evidence: `signalFromNodeResponse` aborts `request.signal` with `ResponseAborted` when the Node response emits `close` before `finish`, which is a real client disconnect. Next's bundled `compression` skips any response whose `Cache-Control` contains `no-transform`. `pipe-readable` calls `res.flush()` after each chunk. If the client goes away, Next cancels the returned body, which cancels `upstream.body`, so the upstream socket closes and uvicorn sees the disconnect. Wrap `fetch` in `try/catch`: a refused connection becomes `TypeError` and should map to 502. An `AbortError` / `ResponseAborted` means the client left, so return nothing meaningful.
- **Upstream SSE facts (installed FastAPI 0.141.1, `fastapi/sse.py` and `routing.py`):** media type `text/event-stream`, sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and sends a `: ping` comment every 15 s while idle. So undici's default 300 s `bodyTimeout` is never hit, and eventsource-parser ignores the comments.
- **Multipart uploads:** (a) **Simplest and validatable:** `const form = await request.formData()`, then check `file instanceof File`, `file.size` and `file.type`, then `fetch(url, { method: "POST", body: form, signal: request.signal })` **without** setting `Content-Type` (undici writes the boundary). This buffers the whole upload in memory, which is fine for transcripts and documents up to a few MB. (b) **Streaming:** `fetch(url, { method: "POST", body: request.body, duplex: "half", headers: { "content-type": request.headers.get("content-type")! }, signal: request.signal })`. Next itself builds the incoming `NextRequest` with `duplex: 'half'` and a stream body. You lose per-field validation, and the size check has to rely on `content-length` or a counting `TransformStream`. TS 5.9's `lib.dom` `RequestInit` has **no `duplex`**, and `@types/node` yields to lib.dom when DOM types are present, so build the init as a typed variable (`const init: RequestInit & { duplex: "half" } = …`), not an inline literal.
- **Body size limits:** route handlers have **no** framework body limit. Enforce your own (reject with 413 on `content-length`, then check `file.size`). `serverActions.bodySizeLimit` (1 MB) applies only to Server Actions. If a `proxy.ts` (formerly middleware) matches the route, Next clones and buffers the body up to `experimental.proxyClientMaxBodySize` (default **10 MB**), and **anything larger is truncated with only a logged warning**. Keep upload routes out of any proxy matcher, or don't add `proxy.ts`.
- **Server-only env:** every non-`NEXT_PUBLIC_` variable stays on the server and is read at request time. Put access in `src/lib/server/env.ts` starting with `import "server-only"`, and parse lazily (`export const serverEnv = () => schema.parse(process.env)` using zod 4 `z.object({ API_BASE_URL: z.url() })`). Never parse at module scope (`next build` loads route modules while it collects page data, and Docker builds have no runtime env; inferred, not verified). Installing `server-only` is optional: Next handles the import internally and ships its own types. Do **not** use `next.config` `env` (it inlines at build time).
- **`output: "standalone"`:** emits `.next/standalone/server.js` (+ traced `node_modules`). Copy `public/` and `.next/static` next to it yourself. It honours `PORT` and `HOSTNAME`. Turbopack chooses the root from the nearest lockfile, so `web/pnpm-lock.yaml` makes `web/` the root. Files **outside** that root (e.g. `../openapi.json`) are not resolved, so keep the OpenAPI snapshot inside `web/`. See topic 7 for the Dockerfile.
- **Lint:** `next lint` is **removed** in 16 (`next build` no longer lints, and the `eslint` key in next.config is gone; codemod `pnpm dlx @next/codemod@canary next-lint-to-eslint-cli .`). Use the ESLint CLI with the flat config the scaffold writes (`defineConfig([...nextVitals, ...nextTs, globalIgnores([...])])` from `eslint-config-next/core-web-vitals` + `/typescript`). That config bundles react, react-hooks v7 (recommended, including the React-Compiler-era rules), @next/next, and a handful of `jsx-a11y` rules as warnings. Scripts: `"lint": "eslint --max-warnings=0"`, `"typecheck": "next typegen && tsc --noEmit"` (route types only exist after typegen). Biome 2.x (`--biome`) is the supported alternative (`biome check`, with Next and React domains), but it covers fewer Next/a11y rules.
- **Turbopack defaults:** `next dev` and `next build` both use Turbopack, and `--webpack` opts out. A custom `webpack()` config makes `next build` **fail**. Config lives at top-level `turbopack` (`rules`, `resolveAlias`, `root`). Filesystem caching for dev and build is on by default, under `.next/cache`.
- **New and useful:** `next typegen`; bundled docs at `node_modules/next/dist/docs/` (the scaffolded `AGENTS.md` points agents there); `connection()` from `next/server` to force request-time evaluation; `RouteContext`/`LayoutProps` globals; graceful shutdown on SIGTERM/SIGINT drains in-flight requests.
- **Avoid:** `export const dynamic`/`runtime`/`revalidate` in handlers; `runtime = 'edge'`; `middleware.ts` (renamed `proxy.ts`; only `nodejs`); fetching your own route handlers from Server Components (the docs say this fails at build and adds a round trip); passing upstream response headers through wholesale (undici decompresses gzip but keeps `content-encoding`, which corrupts the body; build fresh headers); `next start` with standalone output (use `node server.js`); TypeScript 6/7 (TS 7.0.2's main export is only `lib/version.cjs`, so there is no compiler API; typescript-eslint 8.71 peers `typescript <6.1.0` and openapi-typescript 7.13 peers `^5.x`); ESLint 10 (eslint-plugin-react/import/jsx-a11y peers stop at ESLint 9, and the Next docs warn about peer failures).
- **Cache Components decision:** I recommend `--no-cache-components` for this BFF. All data flows through route handlers and client components, so there is nothing to cache, and with it on, pages fail the build on sync IO (`Date.now()`, `crypto.randomUUID()`) or on uncached data outside `<Suspense>`. If kept: no segment-config exports, wrap runtime data in `<Suspense>`, call `await connection()` before reading runtime env in Server Components, and know that a GET handler with no uncached or runtime access **is prerendered at build**. Record the choice in `design.md` (comply or explain).
- **Sources:** Context7 `/vercel/next.js` (lists ≤ v16.2.9) and `/websites/nextjs` (2026-10-06); `next@16.4.0` tarball: `dist/docs/01-app/**` (route.md, route-handlers, backend-for-frontend, route-segment-config, output, streaming, compress, self-hosting, version-16 upgrade, eslint, proxyClientMaxBodySize, turbopack, cli/next.md), `dist/server/web/spec-extension/adapters/next-request.js`, `dist/compiled/compression`, `dist/server/pipe-readable.js`, `dist/server/lib/{start-server,app-info-log,generate-agent-files}.js`; `create-next-app@16.4.0` `--help` + `dist/index.js` + templates; `npm view` peers.

### Tailwind CSS 4.3.3 (with Next 16.4)
- **Use:** CSS-first config. In `globals.css`: `@import "tailwindcss";` then `@theme inline { --color-background: var(--background); … }` mapping CSS variables to tokens, with the values in `:root` / `.dark`. No `tailwind.config.*`. The bundler integration is either the scaffold's `@tailwindcss/turbopack` loader (new package, created 2026-07-31; config shown above) or the PostCSS route in Tailwind's own Next guide (`pnpm add -D tailwindcss @tailwindcss/postcss postcss` + `postcss.config.mjs` `{ plugins: { "@tailwindcss/postcss": {} } }`). Both work with shadcn: its v4 check only needs a CSS file importing tailwind (verified in the `shadcn` bundle).
- **Dark mode:** the default `dark:` variant uses `prefers-color-scheme`. For a toggle, use a class strategy: `@custom-variant dark (&:is(.dark *));` (what shadcn writes) plus `next-themes` `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>`, and `suppressHydrationWarning` on `<html>`.
- **Numbers:** `tabular-nums` (font-variant-numeric) exists in v4.3.3. Use it on estimate tables, durations and costs so digits align while streaming. `font-features-[…]` arbitrary values exist for `tnum` and similar.
- **Patterns:** use tokens (`bg-background`, `text-muted-foreground`, `border-border`), not raw palette classes, for surfaces. `@variant dark { … }` works inside custom CSS. `@source` handles content outside auto-detection.
- **Avoid:** v3 `tailwind.config.js` and `@tailwind base/components/utilities`; `tailwindcss-animate` (use `tw-animate-css`); `postcss-import`/`autoprefixer` (built in).
- **Sources:** Context7 `/websites/tailwindcss` (2026-10-06); tailwindcss.com Next.js framework guide (PostCSS route); `tailwindcss@4.3.3` dist (`tabular-nums`, `font-features`, `custom-variant` present); `@tailwindcss/turbopack@4.3.3` README; create-next-app 16.4 template `globals.css`.

### shadcn CLI 4.21.3 (components copied into the repo; `shadcn` is also a runtime dep for `shadcn/tailwind.css`)
- **Use (non-interactive, inside `web/`):** `pnpm dlx shadcn@4.21.3 init -b radix -p nova -y` (add `--no-monorepo` if it prompts), then `pnpm dlx shadcn@4.21.3 add field input textarea button toggle-group sheet resizable tooltip hover-card skeleton sonner tabs table badge scroll-area card alert spinner empty -y`. Verified `init` flags: `-t/--template`, `-b/--base base|radix|aria`, `-p/--preset [name|code|url]`, `-y` (default true), `-d/--defaults` (= `--template=next --preset=base-nova`), `-f`, `--css-variables` (default), `--rtl`, `--pointer`, `--reinstall`, `--monorepo/--no-monorepo`. Other commands: `apply` (switch presets), `add --dry-run|--diff|--view`, `docs <component>` (agent-friendly docs), `view`, `search`, `info`, `migrate`, `eject`, `mcp`.
- **2026 changes:** **Base UI became the default base in July 2026** (`init` without `-b` gives Base UI). Base UI uses `render={<Button/>}` (+ `nativeButton={false}` for non-buttons) instead of `asChild`, `onOpenChange(open, eventDetails)`, and `data-open`/`data-closed` instead of `data-state`. In Base projects `sonner` is hidden from selection and the Base-only `toast` (`toast.add({ title })`) is offered instead. A third base, React Aria (`-b aria`), exists. CLI v4 (March 2026) brought named presets (`nova`, `lyra`, …) / codes / URLs, `apply`, the `docs` command, and `shadcn/tailwind.css` (custom variants `data-open:` etc. + accordion keyframes; `eject` inlines it). The `new-york` style uses the unified `radix-ui` package (`import { Dialog as DialogPrimitive } from "radix-ui"`). **Recommendation: `-b radix`.** It keeps `sonner`, the `asChild` APIs that most examples and AI Elements assume, and lower overnight risk.
- **components.json (v4):** `"tailwind": { "config": "", "css": "src/app/globals.css", "baseColor": "neutral", "cssVariables": true }`, `"iconLibrary": "lucide"`, `"rsc": true`, aliases `@/components`, `@/components/ui`, `@/lib/utils`, `@/lib`, `@/hooks`, and a `style` like `radix-nova`.
- **Theming:** init writes `@import "tailwindcss"; @import "tw-animate-css"; @import "shadcn/tailwind.css"; @custom-variant dark (&:is(.dark *));`, `@theme inline` token mapping, oklch `:root`/`.dark` variables, and radius scale `calc(var(--radius) * n)`. Extend with your own tokens in `@theme inline` (e.g. `--color-confidence-low`).
- **Components present in the registry today (index.json, 63 ui items):** forms: **`field`** (`Field`, `FieldLabel`, `FieldDescription`, `FieldError`, `FieldGroup`, `orientation="horizontal"`) is the current form primitive, and the legacy `form` item still exists. Also `input-group`, `button-group`, `native-select`, `toggle`/**`toggle-group`** (segmented control), **`sheet`**, `drawer`, **`resizable`** (react-resizable-panels v4; wrapper API unchanged; prop `orientation`, not `direction`), **`tooltip`**, **`hover-card`** (Base: preview-card), **`skeleton`**, **`spinner`**, **`empty`**, **`sonner`** (deps `sonner` + `next-themes`), **`tabs`**, **`table`**, **`badge`**, **`scroll-area`**, `kbd`, `item`. New AI-chat items: `message`, `message-scroller` (dep `@shadcn/react`; `role="log"`, `aria-relevant="additions"`, `aria-busy` while streaming, `autoScroll`, a jump-to-latest button), `bubble`, `attachment`, `marker`, `questionnaire`.
- **Form pattern (RHF + zod):** `useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues })`, then `<Controller name control render={({ field, fieldState }) => <Field data-invalid={fieldState.invalid}><FieldLabel htmlFor={field.name}/><Input {...field} id={field.name} aria-invalid={fieldState.invalid}/>{fieldState.invalid && <FieldError errors={[fieldState.error]}/>}</Field>}/>`. `@hookform/resolvers` 5.9 peers `zod ^3.25 || ^4`, and `import * as z from "zod"` gives v4.
- **Avoid:** `--style`/`--base-color`/`--src-dir` flags (removed in v4); individual `@radix-ui/react-*` packages; mixing Base and Radix component APIs; `tailwindcss-animate`. After init, check that `@theme inline` font lines are not self-referential (`--font-sans: var(--font-sans)`; reported by the Vercel shadcn skill, unverified for 4.21.3).
- **Sources:** Context7 `/shadcn-ui/ui/shadcn_4.21.0` (CLI docs, changelog 2026-03 CLI v4, 2026-04 apply, 2026-07 Base UI default, forms/react-hook-form, resizable, message-scroller, base-vs-radix skill) (2026-10-06); `npx shadcn@4.21.3 init|add|preset --help`; `shadcn@4.21.3` tarball (`dist/tailwind.css`); `https://ui.shadcn.com/r/index.json` and `/r/styles/{radix,base}-nova/sonner.json`.

### openapi-typescript 7.13.0 + openapi-fetch 0.17.0
- **Use:** commit a snapshot generated from the app factory (no server and no keys needed, because settings resolve in the lifespan): `uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > web/openapi.json`. Then `pnpm exec openapi-typescript openapi.json -o src/lib/api/schema.d.ts` (scripts `gen:api` and `check:api` = the same command plus `--check`). Typed client in server-only code:
  `const api = createClient<paths>({ baseUrl: serverEnv().API_BASE_URL })` → `const { data, error, response } = await api.POST("/api/v1/…", { body, signal: request.signal })`. `data` is set only for 2xx and `error` only for 4xx/5xx, and network failures throw.
- **Useful CLI flags (verified with `--help`):** `--check`, `--root-types` (+ `--root-types-no-schema-prefix`, `--root-types-keep-casing`), `--enum`/`--enum-values`/`--dedupe-enums`/`--conditional-enums`, `--export-type`, `--immutable`, `--path-params-as-types`, `--alphabetize`, `--exclude-deprecated`, `--read-write-markers` (7.13 / 0.17: `$Read`/`$Write` wrappers that openapi-fetch strips from request and response types), `--default-non-nullable`, `--properties-required-by-default`.
- **Patterns:** `parseAs: "stream"` returns the raw body, but for the SSE proxy plain `fetch` is simpler (topic 1). Middleware (`onRequest`/`onResponse`/`onError`, also per request since 0.15) is a good place for `x-request-id` propagation. FastAPI with Pydantic v2 emits separate `-Input`/`-Output` schemas when they differ, so expect `components["schemas"]["X-Output"]`.
- **Avoid:** generating from a live URL in CI (use the committed snapshot + `--check`, and regenerate in the Python job and `git diff --exit-code`); importing the client into client components (keep it behind `server-only`); running it under TS 6/7 (peer `typescript ^5.x`).
- **Sources:** Context7 `/websites/openapi-ts_dev` (CLI, openapi-fetch API) (2026-10-06); `openapi-typescript@7.13.0 --help`; CHANGELOGs in both tarballs; `app/main.py`/`app/config.py` (settings resolved in the lifespan).

### eventsource-parser 4.1.1 (browser SSE over POST)
- **Use:** `import { EventSourceParserStream } from "eventsource-parser/stream"`, then
  `const reader = res.body!.pipeThrough(new TextDecoderStream()).pipeThrough(new EventSourceParserStream({ onError: "terminate", maxBufferSize: 1_000_000 })).getReader()` and loop `for (;;) { const { done, value } = await reader.read(); if (done) break; switch (value.event) { case "delta": …JSON.parse(value.data) } }`. `value` is `{ event?: string; id?: string; data: string }`, and `event` is `undefined` for default `message` events. Abort with an `AbortController` passed to `fetch`, so a Stop button cancels the browser, BFF and FastAPI chain.
- **Core API:** `createParser({ onEvent, onError, onRetry, onComment, onId, maxBufferSize })`, `.feed(chunk)`, `.reset({ consume: true })` at end of stream to flush.
- **New in 4.x (4.0.0 on 2026-08-10):** `maxBufferSize` (exceeding it **always** errors the stream), `onId`, `unknown-field` parse errors, and `engines.node >=22.12` (irrelevant once bundled).
- **Avoid:** `for await (const ev of stream)` in browser code. `ReadableStream` async iteration ships in Chrome 124 / Firefox 110 / **Safari 27 only** (MDN BCD 8.1.4), and TS 5.9 types it only under `lib: ["dom.asynciterable"]`, which Next's tsconfig lacks. Use `getReader()`. Also avoid `EventSource` (GET only, no body) and hand-rolled `split("\n\n")` parsing.
- **Sources:** Context7 `/rexxars/eventsource-parser` (2026-10-06); `eventsource-parser@4.1.1` README + package.json; `@mdn/browser-compat-data@8.1.4` (`api.ReadableStream.@@asyncIterator`, `TextDecoderStream`); TS 5.9.3 `lib.dom.asynciterable.d.ts`.

### Testing: Vitest 5.0.3 (+ Vite 8.3.3, RTL 16.3.3, jest-dom 7.0.1, jsdom 30.1.2), Playwright 1.63.0, @axe-core/playwright 4.13.0
- **Vitest config (`vitest.config.mts`):**
  ```ts
  import { defineConfig } from "vitest/config"
  import react from "@vitejs/plugin-react"
  import { fileURLToPath } from "node:url"
  export default defineConfig({
    plugins: [react()],
    resolve: { tsconfigPaths: true, alias: { "server-only": fileURLToPath(new URL("./src/test/empty.ts", import.meta.url)) } },
    test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
  })
  ```
  `setup.ts`: `import "@testing-library/jest-dom/vitest"; import { cleanup } from "@testing-library/react"; import { afterEach } from "vitest"; afterEach(cleanup)`. RTL auto-cleanup only registers when a **global** `afterEach` exists (verified in RTL 16.3.3), so register it yourself unless `globals: true`. For route-handler tests, add `// @vitest-environment node` per file and stub `fetch` (`vi.stubGlobal`).
- **Vitest 5 changes:** `vite` is now a **required peer** (`^6.4 || ^7 || ^8`), so add `vite` explicitly (pnpm auto-installs peers, but be explicit). Requires Node `^22.12 || ^24 || >=26`. `@types/node` optional peer is `^22 || >=24`, so bump the scaffold's `@types/node ^20` to `^24` (matches the Node 24 runtime). Vite 8 has built-in `resolve.tsconfigPaths: true`, so `vite-tsconfig-paths` is unnecessary (Next's bundled Vitest guide still shows the plugin). `@vitejs/plugin-react` 6 peers `vite ^8` only. jsdom 30 needs Node `^22.22.2 || ^24.15.0 || >=26`. happy-dom 20.14.5 is a faster alternative with lower fidelity.
- **server-only in tests:** the npm package's default export **throws** (`exports: { "react-server": "./empty.js", default: "./index.js" }`). Alias it to an empty module as above. Do not set `resolve.conditions: ["react-server"]` globally (that swaps React builds and breaks RTL; inferred). Async Server Components can't be unit-tested in Vitest (Next docs), so cover them with E2E.
- **Playwright 1.63 config:** `use: { baseURL, trace: "on-first-retry", screenshot: "only-on-failure", video: { mode: "on", size: { width: 1280, height: 720 }, show: { actions: { position: "top-right" }, test: { level: "step" } } } }`. `video.show` (action/test overlays) is new. **New `page.screencast.start({ path, size })` / `.stop()`** records ad-hoc clips (or `onFrame` JPEG frames). Make a GIF with ffmpeg (installed: 8.0.1): `ffmpeg -i in.webm -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" out.gif`. Full-page shots: `page.screenshot({ path, fullPage: true })`; visual diffs use `toHaveScreenshot()`, whose baselines are per-platform (darwin and linux differ).
- **Against Docker Compose:** `webServer` errors with **"Process from config.webServer exited early"** if the command exits (verified string in `playwright@1.63.0/lib`), so **never** `docker compose up -d --wait` there. Either run compose outside Playwright (`docker compose up -d --build --wait && pnpm exec playwright test; docker compose down`, the recommended route) and set `baseURL` from env, or use a foreground `webServer: { command: "docker compose up --build", url: "http://localhost:3000/api/health", reuseExistingServer: !process.env.CI, timeout: 180_000, gracefulShutdown: { signal: "SIGTERM", timeout: 30_000 } }` (the docs note that stopping containers needs SIGTERM).
- **axe:** fixture `makeAxeBuilder = () => new AxeBuilder({ page }).withTags(["wcag2a","wcag2aa","wcag21a","wcag21aa","wcag22aa"])`, then `expect((await makeAxeBuilder().analyze()).violations).toEqual([])`. Run it in light **and** dark (`page.emulateMedia({ colorScheme: "dark" })`) and after streaming completes. `wcag22aa` exists in axe-core 4.13 (target-size).
- **Avoid:** real LLM calls in e2e (AGENTS.md rule), which needs a fake provider or upstream stub in the compose test profile; `vite-tsconfig-paths`; `@testing-library/jest-dom` root import with Vitest (use `/vitest`).
- **Sources:** Context7 `/vitest-dev/vitest/v5.0.3` (migration, environment, setupFiles), `/vitejs/vite/v8.0.10` (`resolve.tsconfigPaths`), `/microsoft/playwright/v1.63.0` (webServer, videos, Screencast, accessibility-testing-js) (2026-10-06); `next@16.4.0/dist/docs/01-app/02-guides/testing/{vitest,jest}.md`; tarballs: vitest 5.0.3 (peers/engines), jest-dom 7.0.1 README/exports, RTL 16.3.3 `dist/index.js`, server-only 0.0.1, playwright 1.63.0 `lib/`, axe-core 4.13.0 tags.

### Docker 29.4.3 + Compose v5.1.3, uv 0.12.23, node:24.21.0-slim, redis 8.10.2
- **Compose v5 facts:** v5.0.0 (2025-12-02) removed the internal builder, so **builds always go through Docker Bake / buildx**. Also new in v5: `start --wait`, `build.no_cache_filter`. Don't write `version:`; the file is `compose.yaml`. Local CLI verified: `up --wait --wait-timeout --watch/-w --build -d`, `watch [--no-up --prune --quiet]`.
- **API image (`api.Dockerfile` at the root + `api.Dockerfile.dockerignore`; a Dockerfile-specific ignore file beats the root `.dockerignore`):**
  ```dockerfile
  # syntax=docker/dockerfile:1
  FROM python:3.12-slim-trixie AS base
  COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
  ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 PYTHONUNBUFFERED=1
  WORKDIR /app
  FROM base AS deps-prod
  RUN --mount=type=cache,target=/root/.cache/uv --mount=type=bind,source=uv.lock,target=uv.lock \
      --mount=type=bind,source=pyproject.toml,target=pyproject.toml uv sync --locked --no-install-project --no-dev
  FROM base AS dev
  RUN --mount=type=cache,target=/root/.cache/uv --mount=type=bind,source=uv.lock,target=uv.lock \
      --mount=type=bind,source=pyproject.toml,target=pyproject.toml uv sync --locked --no-install-project
  COPY app ./app
  ENV PATH="/app/.venv/bin:$PATH"
  CMD ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
  FROM python:3.12-slim-trixie AS runtime
  RUN groupadd --system --gid 999 nonroot && useradd --system --gid 999 --uid 999 --create-home nonroot
  WORKDIR /app
  COPY --from=deps-prod --chown=nonroot:nonroot /app/.venv /app/.venv
  COPY --chown=nonroot:nonroot app ./app
  ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
  USER nonroot
  CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
  ```
  Builder and runtime must share the **same base image** (the venv's interpreter path; Astral's note). `[tool.uv] package = false`, so `--no-install-project` is the whole sync. The uv in the image must satisfy `required-version = ">=0.12.18,<0.13"`, which 0.12.23 does. `UV_NO_DEV=1` is the env equivalent of `--no-dev`. The ignore file must keep `app/prompts/**/*.md` (prompt templates are read at runtime) and exclude `.env*`, `.venv`, `web/`, `.git`, caches, `evals/reports`, `data/`.
- **Web image (`web/Dockerfile` + `web/.dockerignore`, following the official `with-docker` example):** stages `deps` (`COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./`, `RUN --mount=type=cache,target=/root/.local/share/pnpm/store corepack enable pnpm && pnpm install --frozen-lockfile`, `ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0`), `dev` (`COPY . .`, `CMD ["pnpm","dev","--hostname","0.0.0.0"]`), `build` (`pnpm build` with `NEXT_TELEMETRY_DISABLED=1`), and `runtime` (`node:24.21.0-slim`, `ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0`, `COPY --from=build --chown=node:node /app/public ./public`, `…/.next/standalone ./`, `…/.next/static ./.next/static`, `USER node`, `CMD ["node","server.js"]`). The official example now uses the image's built-in **`node`** user (uid 1000) rather than a custom `nextjs` user. Either is fine, and `node` saves a layer. Corepack still ships with Node 24 (0.36.0); pnpm 11 needs Node ≥ 22.13.
- **compose.yaml (base = production-like):**
  ```yaml
  services:
    api:
      build: { context: ., dockerfile: api.Dockerfile, target: runtime }
      env_file: [{ path: .env, required: false }]
      expose: ["8000"]                      # no `ports:` → reachable only on the compose network
      healthcheck:
        test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
        interval: 10s
        timeout: 3s
        retries: 5
        start_period: 20s
        start_interval: 1s
    web:
      build: { context: ./web, target: runtime }
      environment: { API_BASE_URL: "http://api:8000" }
      ports: ["3000:3000"]
      depends_on: { api: { condition: service_healthy, restart: true } }
      healthcheck:
        test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]
        interval: 10s
        timeout: 3s
        retries: 5
        start_period: 20s
        start_interval: 1s
    redis:
      image: redis:8.10.2-alpine
      healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, timeout: 3s, retries: 5 }
  ```
  `docker compose up -d --build --wait` blocks until every healthcheck passes (`--wait-timeout N`). `start_interval` needs Engine ≥ 25 (local 29.4.3). Neither slim image ships curl or wget, so the healthchecks use `python`/`node`.
- **compose.dev.yaml (opt-in override; only `compose.override.yaml` is auto-merged):** run with `docker compose -f compose.yaml -f compose.dev.yaml up --build --watch` (or `… watch`).
  ```yaml
  services:
    api:
      build: { target: dev }
      develop:
        watch:
          - { action: sync, path: ./app, target: /app/app }
          - { action: rebuild, path: ./uv.lock }
          - { action: rebuild, path: ./pyproject.toml }
    web:
      build: { target: dev }
      develop:
        watch:
          - { action: sync, path: ./web, target: /app, ignore: [node_modules/, .next/] }
          - { action: rebuild, path: ./web/package.json }
          - { action: rebuild, path: ./web/pnpm-lock.yaml }
  ```
  Watch actions: `sync`, `sync+restart` (≥2.23), `sync+exec` (+ `exec.command`, ≥2.32), `rebuild`, `restart` (≥2.32), plus `initial_sync` and `ignore`/`include`. The image needs `stat`, `mkdir` and `rmdir`, and the container **USER must be able to write the target** (use `COPY --chown`, or run dev targets as root, as Astral's compose example does with `user: root`). uvicorn `--reload` and Next dev pick up synced files because they arrive as real in-container writes.
- **env_file semantics:** values come **from the file only**, and plain `KEY=value` lines are **not** overridden by the host shell. Precedence: `run -e` > `environment`/`env_file` values *interpolated* from shell/.env > `environment` literal > `env_file` > image `ENV`. `required: false` (≥2.24) makes the file optional, and `format: raw` disables interpolation. Separately, Compose auto-loads the project-dir `.env` **for `${VAR}` interpolation in compose.yaml only**. So prefer `env_file:` over `environment: { ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY} }`, which would read the host shell and conflicts with the "never export the key globally" rule.
- **Redis:** official `redis` image, latest `8.10.2` (`8.10.2-alpine`, `8.10.2-trixie`). Keep it internal (no `ports:`). Redis 8 is tri-licensed (RSALv2/SSPL/AGPLv3); `valkey/valkey` is the BSD alternative if that matters.
- **Avoid:** `ghcr.io/astral-sh/uv:latest` (pin it); `python:3.12-slim` in one stage and `-bookworm` in another; secrets in images (`.env*` must be in every ignore file); `HOSTNAME` left at Docker's default (it holds the container ID, so set `HOSTNAME=0.0.0.0` for `server.js`); `version:` keys; publishing api/redis ports.
- **Sources:** Context7 `/websites/astral_sh_uv` (Docker guide: intermediate layers, cache mount, `UV_COMPILE_BYTECODE`, compose watch) and `/docker/docs` (compose `develop`, healthcheck, depends_on, env_file, precedence, file-watch prerequisites, Dockerfile-specific ignore files, gha cache) (2026-10-06); `astral-sh/uv-docker-example` (`Dockerfile`, `multistage.Dockerfile`, `compose.yml`); `vercel/next.js` `examples/with-docker` (Dockerfile, .dockerignore); `docker/compose` v5.0.0 release notes; Docker Hub tags (node, python, redis); GitHub releases (uv 0.12.23, 2026-10-03); ghcr manifest check for `uv:0.12.23`; local `docker compose up|watch --help`.

### GitHub Actions: pnpm/action-setup v6.1.0, actions/setup-node v7.0.0 (+ checkout v7.0.1)
- **Pins (SHA # tag, via `git ls-remote`):** `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1` · `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0` · `pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0` · `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1` · `docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1` · `docker/bake-action@018cb6412ab401ebaa809aa5f85966b74628600f # v7.4.0`. The checkout and setup-node SHAs match the existing `ci.yml`.
- **Concise web job:**
  ```yaml
  web:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: web } }   # does NOT apply to `uses:` steps → paths below are repo-relative
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with: { node-version: "24" }
      - uses: pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0
        with: { package_json_file: web/package.json, cache: true, cache_dependency_path: web/pnpm-lock.yaml }
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm typecheck        # next typegen && tsc --noEmit
      - run: pnpm test             # vitest run
      - run: pnpm check:api        # openapi-typescript … --check
  ```
  Order: setup-node first, because pnpm 11 needs Node ≥ 22.13 and the runner's default Node may be older (unverified for current `ubuntu-latest`). Then pnpm/action-setup, which reads `packageManager` from `package_json_file` and caches the store itself through `cache: true`. If you prefer setup-node's `cache: pnpm` instead, pnpm must be installed **before** setup-node (its docs order: pnpm/action-setup, then setup-node). setup-node v7's only breaking change is the move to ESM. Since v6 it auto-caches only npm; pnpm needs explicit `cache`. pnpm/action-setup v6 has `standalone` (pnpm ≤11 → @pnpm/exe), and `pnpm/setup` is a newer single action that installs pnpm v11+ plus a runtime.
- **`docker compose build` cost:** under Compose v5 this is a Bake build. Cold on a hosted runner, expect roughly 2–4 min for the Next standalone image (pnpm install + Turbopack build) and about 1 min for the uv image (estimate, not measured). Keep it out of the per-push fast path: run it in a separate job (path filter on `web/**`, `app/**`, `*Dockerfile*`, `compose*.yaml`, lockfiles) with `docker/setup-buildx-action` + `docker/bake-action` (`files: compose.yaml`, `set: |\n *.cache-from=type=gha\n *.cache-to=type=gha,mode=max`, `load: true`). `docker compose config -q` is a near-free validation step for every push. The GHA cache backend requires cache API v2 (Buildx ≥ 0.21, Compose ≥ 2.33.1; hosted runners are current).
- **Avoid:** floating tags; `pnpm install` without `--frozen-lockfile`; pnpm/action-setup `version:` that disagrees with `packageManager` (it errors, unverified for v6).
- **Sources:** `git ls-remote --tags` for each action; `action.yml` + README at `pnpm/action-setup@v6.1.0` and `actions/setup-node@v7.0.0` (+ `docs/advanced-usage.md`); Context7 `/docker/docs` (gha cache backend, bake with compose files) (2026-10-06); repo `.github/workflows/ci.yml`.

### Enterprise AI UX references + WCAG 2.2 for streaming (links verified 2026-10-06)
- **Microsoft HAX Guidelines for Human-AI Interaction (18 guidelines, CHI 2019):** https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/. The ones that map to the estimator: G1 make clear what the system can do, **G2 make clear how well it can do it** (confidence and ranges), G9 support efficient correction (editable line items), **G11 make clear why the system did what it did** (basis per estimate), G15 granular feedback, G8 support efficient dismissal (Stop/cancel).
- **Google PAIR People + AI Guidebook:** https://pair.withgoogle.com/guidebook/ (v2: https://pair.withgoogle.com/guidebook-v2/). Chapters: https://pair.withgoogle.com/chapter/explainability-trust/ and https://pair.withgoogle.com/chapter/errors-failing/.
- **NN/g:** topic hub https://www.nngroup.com/topic/ai/; "AI: First New UI Paradigm in 60 Years" https://www.nngroup.com/articles/ai-paradigm/; "Explainable AI in Chat Interfaces" https://www.nngroup.com/articles/explainable-ai/; "AI Hallucinations: What Designers Need to Know" https://www.nngroup.com/articles/ai-hallucinations/; "Prompt Controls in GenAI Chatbots" https://www.nngroup.com/articles/prompt-controls-genai/.
- **Shape of AI pattern library:** https://www.shapeof.ai/ (categories: Wayfinders, Prompt actions, Tuners, Governors, Trust builders, Identifiers). Relevant patterns: https://www.shapeof.ai/patterns/stream-of-thought, `/patterns/citations`, `/patterns/caveat`, `/patterns/controls`, `/patterns/regenerate`, `/patterns/verification` (also Cost estimates, Draft mode, Action plan under Governors).
- **WCAG 2.2 for streaming UIs:** SC 4.1.3 Status Messages (AA) https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html, implemented with ARIA22 `role="status"` https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA22 and ARIA19 `role="alert"` for errors https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA19. MDN live regions: https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions. WAI-ARIA 1.2 `aria-live`/`aria-busy`: https://www.w3.org/TR/wai-aria-1.2/#aria-live. Rules: keep the live region **in the initial markup, empty**, and update it in a later task. `role="status"` implies `aria-live="polite"` and `role="log"` is polite too (add the attribute redundantly for compatibility). `aria-atomic` defaults to false and `aria-relevant` to `additions text`. **Do not** stream every token into a live region (it gets re-announced constantly). Announce phase changes ("Generating estimate…", "Estimate ready: 6 items, 42–58 h") in a polite status region, set `aria-busy="true"` on the output container while streaming, and send errors through `role="alert"`. Provide a visible Stop control (2.2.2 Pause, Stop, Hide: https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html). Also new-in-2.2 criteria worth testing: 2.4.11 Focus Not Obscured (sticky headers/sheets) and 2.5.8 Target Size Minimum (24×24, which axe `wcag22aa` checks).

### Gotchas for the implementers
1. **next 16.4.0 is day-zero (published today).** pnpm 11's new default `minimumReleaseAge: 1440` (non-strict) won't resolve versions under a day old unless nothing else satisfies the range. Exact pins from create-next-app still install, but `pnpm dlx create-next-app@latest` could resolve differently, so always pin `@16.4.0`. If 16.4.0 misbehaves, 16.3.8 is the fallback; the bundled docs I grounded on are from 16.4.0.
2. **pnpm 11 defaults:** `strictDepBuilds: true` means install **fails** when a dependency with build scripts isn't listed in `pnpm-workspace.yaml` `allowBuilds:` (the scaffold pre-lists `sharp: false, unrs-resolver: false`; add others as `true`/`false` when pnpm complains). Also `verifyDepsBeforeRun: install` and `blockExoticSubdeps: true`. `pnpm-workspace.yaml` must be COPYed into the Docker deps stage.
3. **create-next-app `--yes` reuses saved preferences.** Pass every flag (or `--reset`). Its defaults turn on `cacheComponents`, `partialPrefetching` and `experimental.agentFeedback`. The latter makes `next dev` inject a feedback block into `AGENTS.md` that tells agents to run `next internal agent-feedback-instructions` (a network call). Pass `--no-agent-feedback`. `next dev` also re-writes the `nextjs-agent-rules` block in `web/AGENTS.md` whenever it detects an AI agent; commit it, or set `agentRules: false` in next.config.
4. **Keep TypeScript `^5` (5.9.3) and ESLint `^9`,** as scaffolded. TS 7.0.2 has no JS compiler API (main export is `lib/version.cjs`), which breaks typescript-eslint (`<6.1.0`) and openapi-typescript (`^5.x`). ESLint 10 triggers peer failures in eslint-plugin-react/import/jsx-a11y. Bump `@types/node` to `^24` (Vitest 5 peer + Node 24 runtime).
5. **`next lint` no longer exists, and `next build` no longer lints.** CI must run `eslint` and `next typegen && tsc --noEmit` explicitly. Without typegen, `RouteContext`/`LayoutProps` are unknown to `tsc`.
6. **SSE through the BFF:** return `new Response(upstream.body, …)` with **fresh** headers (`text/event-stream`, `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`). `no-transform` is what stops Next's gzip. Never copy upstream `content-encoding`/`content-length`/`transfer-encoding`/`connection`. Always pass `signal: request.signal`. On the client, read with `getReader()`, not `for await`.
7. **`duplex: "half"` is not in TS 5.9's DOM `RequestInit`.** Build the init as a typed variable (`RequestInit & { duplex: "half" }`). It is only needed when forwarding `request.body` as a stream.
8. **No body-size limit on route handlers.** Validate `content-length` and `File.size` yourself. Adding a `proxy.ts` that matches upload routes silently **truncates bodies over 10 MB**.
9. **Turbopack root = `web/`** (from `web/pnpm-lock.yaml`), so imports from outside `web/` don't resolve. Keep `openapi.json` and `schema.d.ts` under `web/`. A custom `webpack()` config fails `next build`.
10. **Env:** read `process.env` lazily inside handlers (`serverEnv()`), never at module scope, and never through `next.config` `env` or `NEXT_PUBLIC_` for the API URL. The browser must only ever call `/api/*` on Next; FastAPI has no published port.
11. **Standalone in Docker:** set `HOSTNAME=0.0.0.0` (Docker sets `HOSTNAME` to the container ID), copy `public/` and `.next/static`, and run `node server.js`, not `next start`. If `public/` is deleted, the `COPY` fails, so keep the folder.
12. **`next/font/google` (Geist in the template) downloads fonts at build time.** Docker and CI builds need network. Use the `geist` npm package (1.7.2) or `next/font/local` for offline or hermetic builds.
13. **API image ignore file:** do **not** copy the Next example's `*.md` exclusion. `app/prompts/v*/system.md` is read at runtime by `app/prompts/loader.py`. Exclude `.env*`, `.venv`, `web/`, `.git`, `evals/reports`, `data/`.
14. **uv in Docker:** pin `ghcr.io/astral-sh/uv:0.12.23` (it must satisfy `required-version <0.13`), use the same Python base image in build and runtime, set `UV_PYTHON_DOWNLOADS=0`, and use `uv sync --locked`. A `uv.lock` change requires a rebuild (watch `rebuild` action), not a sync.
15. **Compose watch + non-root:** sync fails if the container USER can't write the target. Dev targets either run as root (local only) or `COPY --chown`. Ignore `node_modules/` and `.next/` in the web sync, because macOS-built `node_modules` must never reach the Linux container.
16. **`env_file:` keeps host-shell keys out** (plain values are not overridden by the shell). Compose's auto-loaded root `.env` only feeds `${…}` interpolation in compose.yaml. Don't interpolate API keys from the shell.
17. **Playwright + compose:** `webServer` fails if the command exits ("exited early"), so bring the stack up with `docker compose up -d --build --wait` outside Playwright, or use foreground `up` plus `gracefulShutdown: { signal: "SIGTERM" }`. E2E must not hit real LLMs; plan a fake provider or stub for the compose test run.
18. **shadcn 4.21 defaults to Base UI.** Pass `-b radix` explicitly if you want `sonner`, `asChild` and Radix-based examples. Don't mix the two bases' APIs (`render` vs `asChild`, `data-open` vs `data-state`). `shadcn` stays a runtime dependency because of `@import "shadcn/tailwind.css"`.
19. **Vitest 5:** add `vite` explicitly, alias `server-only` to an empty module, register `afterEach(cleanup)` (no globals), and prefer `resolve.tsconfigPaths: true` over `vite-tsconfig-paths`.
20. **GitHub Actions `defaults.run.working-directory` does not apply to `uses:` steps.** Give action inputs repo-relative paths (`web/package.json`, `web/pnpm-lock.yaml`).

### Task 6 learnings (2026-10-07, web scaffold)
- create-next-app 16.4.0 and shadcn 4.21.3 (`-b radix -p nova`) worked as documented; shadcn init left `--font-sans: var(--font-sans)` self-referential in `@theme inline` (confirmed): point it at `var(--font-geist-sans)`. Its `layout.tsx` still uses `next/font/google`; swap to `geist/font/sans` and `geist/font/mono` (`GeistSans.variable`, `GeistMono.variable`).
- Scaffold's `pnpm-workspace.yaml` listed `allowBuilds` only for `sharp` and `unrs-resolver` (both `false`); no further entries were needed for the deps above. `next build` works with `output: "standalone"` and passes with an empty `public/`.
- Custom Tailwind utility: `@utility num { font-variant-numeric: tabular-nums; }`. `@theme inline` keys `--text-sm` plus `--text-sm--line-height` set the type scale.
- Vitest 5 + Vite 8 `resolve.tsconfigPaths` and the `server-only` alias work as written above; `vi.mock("server-only")` is unnecessary.
- Fix round 1 facts: (a) `web/pnpm-workspace.yaml` `minimumReleaseAgeExclude` was written by create-next-app 16.4.0 because next 16.4.0 (and its `@next/*` siblings) was under 24 h old; pnpm 11 would otherwise refuse them. Entries can be dropped once the release ages out. (b) The runtime dep `shadcn` resolved to 4.21.2 while the CLI used for init/add is pinned 4.21.3 (harmless skew; only `shadcn/tailwind.css` is imported). (c) shadcn's `src/lib/utils.ts` now re-exports `cn` from the `cn` npm package (no clsx/tailwind-merge). (d) Tailwind v4 duration utilities read `--transition-duration-*`, tw-animate-css reads `--animation-duration-*`; `--default-transition-duration` sets the default; define them in `@theme inline`. `--text-*: initial;` clears the default type scale. (e) Generated shadcn controls use `outline-none`/`outline-hidden` (utilities layer), so a base-layer `:focus-visible` rule never shows: put the focus rule unlayered. (f) `z.httpUrl()` (zod 4.6) requires a dotted hostname (TLD), rejecting `http://ai-service:8000` and `http://localhost`; use `z.url({ protocol: /^https?$/ })`.

### Task 7 learnings (2026-10-07, BFF route handlers)
- **Client-left detection:** when `request.signal` aborts, undici's `fetch` rejects with the signal's **reason** (Next aborts with its own `ResponseAborted` error), not a `TypeError` and not always an `AbortError` (verified in Node 24.21). Check `request.signal.aborted` first, then `error instanceof TypeError` (refused/unreachable/connect timeout, `cause` carries e.g. `ECONNREFUSED`). This project maps the `TypeError` case to **503 `upstream_unavailable`** in the AI service's error shape `{error: {code, message}, request_id}` (supersedes the "map to 502" line above).
- **Body cap:** Node's `Request` keeps a caller-set `content-length` (undici enforces no forbidden headers), but a string or chunked body has no `content-length` until sent, so check the header and then count bytes while reading `request.body` (`ReadableStream<Uint8Array<ArrayBuffer>>` in TS 5.9) and `reader.cancel()` once over. `new Blob(chunks)` is a valid `fetch` body (undici sets `content-length`). A GET `Request` has `body === null`; passing any body with GET makes `fetch` throw a `TypeError`.
- **Verified live (next dev 16.4 + uvicorn replay):** SSE partials arrive through the BFF ~100 ms apart with `accept-encoding: gzip` (no compression, no buffering); a client disconnect logs `outcome=cancelled` upstream within ~1 s; the `?refresh=true` allowlist reaches uvicorn and other params do not. `next build` lists the three handlers as `ƒ` without `AI_SERVICE_URL` at build time. `next dev` did not touch tracked files.

### Task 8 learnings (2026-10-07, `useEstimateStream`)
- **eventsource-parser 4.1.1 `onError: "terminate"`** errors the stream on *any* `ParseError`, not only `max-buffer-size-exceeded`: also `unknown-field` (a field other than `event`/`data`/`id`/`retry`) and `invalid-retry` (verified in `src/parse.ts`). FastAPI's `EventSourceResponse` only emits those four fields plus `:` comments, so this is safe here; `reader.read()` then rejects, which the hook maps to `stream_interrupted`. `EventSourceParserStream` has no `flush`, so a final event without its blank line is dropped at EOF (per the SSE spec) and counts as "no terminal event".
- **Testing a streaming hook without act warnings (RTL 16.3.3, React 19.3):** feed the body through a `ReadableStream` whose controller the test holds; `push` chunks, then immediately `await waitFor(...)`. RTL's `asyncWrapper` sets `IS_REACT_ACT_ENVIRONMENT = false` synchronously on entry and drains a macrotask before restoring it, so updates caused by the push land inside it. A mocked `fetch` should honour `init.signal` (error the body on abort) so the abort path runs as with undici. In Vitest's jsdom environment Node's `Response`, `ReadableStream` and `TextDecoderStream` interoperate fine.
- **TS 5.9:** `Record<string, unknown>` is assignable to an all-optional mapped type such as `DeepPartial<EstimationBreakdown>` without a cast. That only checks the **top level**: the hook guarantees a partial is a plain object, but every nested field (arrays, items, numbers, strings, enums) is unchecked wire data whatever the type claims. The view reads each one through a guard (`web/src/lib/estimate/read.ts`) and renders anything missing or malformed as a skeleton.

### Task 9 learnings (2026-10-07, estimate view)
- **Radix HoverCard 1.1.24 (`radix-ui` 1.7.0):** the trigger opens on pointer hover (mouse/pen only, `excludeTouch`) and on keyboard **focus**, and closes on blur. It calls `preventDefault()` on `touchstart`, which cancels the tap's click and focus, so on touch it never opens by itself: make it controlled (`open`/`onOpenChange`) and open it from `onPointerDown` when `pointerType === "touch"` (pointer events fire before touch events). The content is portaled and its tabbables get `tabindex=-1`, so give the trigger `aria-describedby` pointing at an `sr-only` copy of the content for screen readers. In jsdom (30.1.2) the hover card opens on `focus()` after `openDelay` with no `ResizeObserver` stub needed.
- **`cn` 0.4.0 merges Tailwind conflicts** (it replaces clsx + tailwind-merge): `cn("animate-pulse", "animate-none …")` drops `animate-pulse`, so shadcn primitives can be overridden through `className`.
- **Skeleton placeholders:** shadcn's `Skeleton` renders a `div`, which is invalid inside `h2`, `span`, `p` or `dt`. Inline placeholders (`Pending`) are a `span.block` with the same `bg-muted rounded` styling and `data-slot="skeleton"`. They pulse only while the estimate's `<article aria-busy>` streams: `motion-safe:group-aria-busy/estimate:animate-pulse`.
- **Table semantics:** each task row's first cell is `<th scope="row" aria-labelledby={nameId}>` so Range and Expected cells announce the task name only, not its rationale (WCAG 1.3.1). Phase rows are `th scope="rowgroup"`; Testing Library maps both to `rowheader`, so tests tell them apart by `scope`. In a `table-fixed` table, long unbroken tokens need `wrap-anywhere` (`overflow-wrap: anywhere`; Tailwind 4.3 also has `wrap-break-word`; `break-words` is the legacy name).
- **Lists:** Tailwind preflight sets `list-style: none`, and Safari/VoiceOver then drops list semantics, so unstyled `ul`/`ol` get `role="list"` (styled `list-disc` lists keep theirs).
- **Live regions:** shadcn `Alert` hard-codes `role="alert"` before spreading props, so pass `role={undefined}` for a static warning that must not compete with the view's single polite "Estimate ready" region.
- **Table on narrow screens:** `display: none` cells (`hidden sm:table-cell`) misalign rows that use `colSpan`, so the tasks table keeps three columns (task with rationale and basis, range, expected) and `table-fixed`, which also stops columns resizing while rows stream in. It fits 360 px without horizontal scroll.
- **Intl (Node 24 / evergreen browsers):** `Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })` is valid (the minimum fraction digits default drops to the maximum), giving `$5,700`.
- **Avoid `Map.groupBy` in client code:** Next 16's default browserslist (`next/dist/shared/lib/modern-browserslist-target.js`: chrome 111, edge 111, firefox 111, safari 16.4) predates it (Safari 17.4), and Next does not polyfill it; group with a `Map` loop instead.

### Task 10 learnings (2026-10-07, chat page)
- **sessionStorage thread without a hydration mismatch:** read storage in a lazy `useState(load)` initializer (the pattern in `next@16.4.0/dist/docs/01-app/02-guides/preventing-flash-before-hydration.md`, "Syncing with React state"; `load` returns `[]` when `typeof window === "undefined"`) and render the thread only once hydrated: `useSyncExternalStore(() => () => {}, () => true, () => false)` is `false` on the server and during hydration, `true` after. The usual `useEffect(() => setX(load()), [])` is flagged by `react-hooks/set-state-in-effect` (on in eslint-config-next 16.4), and an inline script cannot rebuild a React-rendered list. Persist from an effect (writing storage is a side effect, not a state update).
- **`useEffectEvent` is stable in React 19.3** (exported and typed in `@types/react`). Use it for the handler a document listener calls (Esc stops the stream) so the effect depends only on whether it is streaming.
- **Escape and Radix layers:** Radix `DismissableLayer` (menus, hover cards) listens for Escape on the document in the **capture** phase and calls `preventDefault()` before dismissing, so a bubble-phase `document` listener skips handled presses with `if (event.defaultPrevented) return`.
- **Focus after a status change:** removing the focused element moves `document.activeElement` to `body`, in browsers and in jsdom 30.1.2 (verified by tests). A message checks for that after its status changes (never on mount) and focuses its first action: Stop → Regenerate, Regenerate → Stop, stream ends under Stop → Copy or the error card's action. Sending refocuses the textarea first, so a finished stream never steals focus from it.
- **Accessible names in tests:** dom-accessibility-api 0.5.16 (used by jest-dom and Testing Library) trims each inline child's text, so `50,000<span class="sr-only"> characters</span>` computes as "50,000characters". Keep the space in the preceding text node (`` {`${n} / ${limit} `}<span className="sr-only">characters</span> ``, or `{" "}`); browsers announce the same string.
- **Scroll containers with `sr-only` descendants must be `relative`:** `sr-only` is `position: absolute`; without a positioned ancestor its containing block is the viewport, and its static position deep inside an `overflow-y-auto` region extends the **document's** scrollable overflow. `scrollIntoView` then scrolls the page too and hides the header (seen in Chromium). `main.relative` fixes it.
- **Next's route announcer is `role="alert"`** (`#__next-route-announcer__`, always in the DOM), so an e2e `getByRole("alert")` matches two elements; scope it (`[data-slot="alert"]`, or within the message).
- **Sample transcripts:** the page Server Component reads `src/content/samples/*.md` with `fs.readFile(path.join(process.cwd(), "src", "content", "samples", …))` and passes the text to client components as props; `/` stays static (○) and `next build` reports no tracing warning. Turbopack can import text directly (`turbopack.rules[…].type: "text"` or `with { turbopackLoader … }`, both 16.2+), but Vitest would then need its own loader.
- **sonner 2.0.8:** `offset` and `mobileOffset` accept `{ top: 56 }` objects; used to keep toasts below the 48 px header and clear of the docked composer. Its `<section aria-live="polite">` is always mounted, so copy confirmations are announced.
- **Visual checks from a worktree:** the Playwright MCP server may only write under the main checkout (`.playwright-mcp/`), which a worktree track must not touch. Drive the app with a Node script that `require`s `web/node_modules/@playwright/test` (+ `@axe-core/playwright`) and writes screenshots to the scratchpad; the AI service runs keyless with `LLM_PROVIDER=replay` (it synthesises a stream from fixture breakdowns when no cassette matches).
- **Fix round 1 facts:** (a) **IME:** a keydown that ends or cancels an IME composition has `isComposing === true` in Chrome and Firefox, but Safari fires `compositionend` *before* the keydown, so only `keyCode === 229` reveals it; guard every text-field shortcut (Esc to stop, Cmd/Ctrl+Enter to send) with `event.isComposing || event.keyCode === 229`. (b) **Reading state that is not rendered yet:** a result frame can be applied (`setState`) but not yet rendered when the next click arrives, so `send`/`regenerate` read `useEstimateStream().current()`, a ref that every transition (`commit`) updates before calling `setState`. Testing that window: do the push, a `setTimeout(0)` and the call inside one `await act(async () => …)`, because act holds the render until it exits. (c) **Accessible name vs description:** text inside a button is part of its name even when an `aria-describedby` points at it; mark the description `aria-hidden` (a description reference still reads hidden content). (d) **Focus recovery is scoped:** track "focus was last in this message" with React `onFocus`/`onBlur` on the root (a `null` relatedTarget, meaning focus fell to the page, keeps the flag) and set it on the message's own action clicks, because Safari does not focus a clicked button; refocus with `focus({ preventScroll: true })`. (e) **Radix `onCloseAutoFocus`** runs after the menu's close animation, with the latest props, so a pick can decide there whether focus goes to the textarea or to a "Replace your draft?" confirmation.

### Task 11 learnings (2026-10-07, inspector)
- **shadcn radix-nova `TabsTrigger` contrast:** the inactive trigger's `text-foreground/60` on the `bg-muted` list fails axe `color-contrast` (WCAG 1.4.3) in the light theme; `web/src/components/ui/tabs.tsx` now uses `text-muted-foreground`. Radix `TabsContent` renders with `tabIndex=0`, so a tab panel that is also the scroll container is keyboard-scrollable without extra attributes.
- **Radix Dialog as a sheet (`radix-ui` 1.7.0):** `DialogTrigger` sets `aria-haspopup="dialog"` and `aria-expanded`; the content traps Tab/Shift+Tab, Esc closes it, and focus returns to the trigger only after the exit animation unmounts it (in Playwright wait for the dialog to be `detached` before asserting focus). Pass `aria-describedby={undefined}` to `SheetContent` when there is no `SheetDescription` (no console warning). Axe and screenshots taken right after opening see the 150 ms fade-in (axe reported 0 contrast issues mid-animation); wait for it.
- **Responsive panel vs sheet without a hydration flash:** render both and let CSS choose (`hidden lg:flex` on the `<aside>`, `lg:hidden` on the header trigger). A `matchMedia` hook would need a server snapshot and shift the layout on hydration; `display: none` also keeps the hidden copy out of the accessibility tree. jsdom applies no CSS, so unit tests see both; the breakpoint itself is a browser check.
- **Scrollable code blocks:** a focusable `<pre tabIndex={0}>` needs a role to carry a name (`aria-label` on a generic element is prohibited), so it is `role="region"` named by its heading. Do not also name the wrapping `<section>`, or there are two regions with the same name. `whitespace-pre-wrap wrap-anywhere` keeps the single-line reference JSON inside the panel width.
- **`next dev` only serves its dev resources to the host it announces:** opening `http://127.0.0.1:<port>` logs "Blocked cross-origin request to Next.js dev resource /_next/hmr" and in our run the page never hydrated; use `http://localhost:<port>` in local Playwright scripts (or list the host in `allowedDevOrigins`).
- **Fix round 1 facts:** (a) the global `:focus-visible` rule is unlayered, so it beats every Tailwind utility for `outline-*`; to change one property for a component use the important modifier (`focus-visible:-outline-offset-2!`, verified computed `outline-offset: -2px` in Chromium). A focusable scroll container (the tab panel) needs that inset ring, since an outer ring is clipped by the viewport edges. (b) Radix `TabsContent` unmounts inactive panels (no `forceMount`), so tests query only the active `tabpanel`. (c) Sheet that must not outlive its breakpoint: control `open`, listen to `matchMedia("(min-width: 1024px)")` `change` only while open, and in `onCloseAutoFocus` call `event.preventDefault()` and focus the panel (`<aside tabIndex={-1}>`, React 19 `ref` prop) when the query matches, because the trigger is `display: none` by then. jsdom has no `matchMedia` (`vi.stubGlobal("matchMedia", …)`; `window === globalThis` there). (d) "Last call" is the last call that *finished*: `useThread` keeps it in state, set from `current()` when the next stream starts and seeded from the latest stored turn on reload; a turn's `kept` estimate is not a newer call.
