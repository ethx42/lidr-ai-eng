# Tech stack brief

stack-fingerprint: fdb14250a109
updated: 2026-10-06

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
  - **Make it a direct dependency** (`jiter>=0.17.0`). Today it is only transitive: openai 3.19.0 requires `jiter>=0.16.0,<1` and anthropic 1.8.0 requires `jiter>=0.4.0,<1` (both METADATA). It is MIT-licensed, released 2026-09-12, and is the latest version.
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
