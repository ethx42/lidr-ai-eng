## Context

See proposal.md for motivation. Checked against the installed packages on 2026-09-23 (anthropic 1.8.0, openai 3.19.0, httpx2 2.13.0):

- `anthropic._base_client` logs `Request options: {...}` at DEBUG, including `json_data` (the full system prompt and transcription). Reproduced with a mock transport and `configure_logging("DEBUG")`: the transcription appeared in the JSON logs. openai 3.19.0 logs only the method at that point (`# Request bodies ... can contain private data`).
- Third-party loggers that see requests: `anthropic`, `openai`, `httpx2`, and `httpcore2` (the transport under httpx2). Their child loggers (`anthropic.lib.*`, `openai.lib.*`, `httpcore2.*`) set no level of their own, so they inherit the parent's.
- `anthropic` sets its own logger level only when `ANTHROPIC_LOG` is set, at import time. `configure_logging` runs later, in the app lifespan.
- Both providers raise `LLMError` subclasses `from` the SDK exception, and both SDKs' `APIStatusError` expose `status_code`. The invalid-output paths that have no SDK exception are Anthropic `stop_reason in INVALID_STOP_REASONS`, OpenAI `status == "incomplete"` (with `incomplete_details.reason`), and a `None` parsed output.
- `JsonFormatter` writes only `exc_type` when a record has `exc_info`.

## Goals / Non-Goals

**Goals:**
- No log record contains the transcription at any level, and a test keeps it that way for both providers.
- An operator can tell from one `llm_call` record why a call failed.
- A third provider gets both behaviours without touching the service, HTTP layer, or logging code.

**Non-Goals:**
- Redacting content inside third-party log messages, and log shipping or retention policy.
- Changing the default `LOG_LEVEL` (the course brief fixes it at `DEBUG`).
- The items listed under "Explicitly deferred" in the proposal.

## Decisions

### D1. Cap third-party client loggers at INFO in `configure_logging`
`observability.py` holds one tuple, `CLIENT_LOGGERS = ("anthropic", "openai", "httpx2", "httpcore2")`. `configure_logging` sets each of them to `max(configured level, INFO)`. The app's own loggers still follow `LOG_LEVEL`. At INFO these libraries log only request lines and retry notices (method, URL, status), which remain useful.
- *Why:* one place, independent of how any SDK formats its messages. A new provider SDK is one more name in the tuple, and the leak test fails if it is forgotten.
- *Rejected:* a logging filter that redacts the transcription. It needs the request's transcript inside the filter (per-request state in a global filter) and depends on SDK message formats. *Rejected:* changing the default to `INFO`, which contradicts the course brief and the `configuration` spec, and still leaks for anyone who sets `DEBUG`.
- Because `configure_logging` runs after the SDK imports, the cap also overrides `ANTHROPIC_LOG=debug`. This is intended: it trades SDK debugging for the no-content guarantee. To debug, run a scratch script without the app's logging setup.

### D2. The failure cause is derived generically on `LLMError`
`LLMError.__init__` gains an optional keyword `reason: str | None`. Two read-only properties go on the base class:
- `cause`: `reason` if given, else the class name of `__cause__` (the chained SDK or pydantic exception), else `None`.
- `upstream_status`: `getattr(__cause__, "status_code", None)`.

Providers pass `reason` only on the invalid-output paths without an exception: Anthropic `f"stop_reason:{stop_reason}"`, OpenAI `f"incomplete:{incomplete_details.reason}"`, and `"no_parsed_output"` for both. `EstimationService` passes `exc.cause` and `exc.upstream_status` to `log_llm_call`. Those two fields are added to the record only when the call failed. The client-facing message stays the class default, so nothing new reaches the HTTP response.
- *Why:* the providers already chain with `raise ... from exc`, so a third provider that follows the same pattern gets the cause for free. Only the class name and status are read. The SDK exception's message and body are never touched.
- *Rejected:* each provider's `map_error` copying fields onto the error. That duplicates the same extraction in every adapter. (The review summary suggested it; this is the simpler form of the same behaviour.)

### D3. Unhandled-error records carry stack locations, not messages
When a record has `exc_info`, `JsonFormatter` adds `stack`: a list of `"file:line in function"` from `traceback.extract_tb`, alongside `exc_type`. The exception message is still not logged. Pydantic `ValidationError` messages, for example, include `input_value`, which can be model output quoting the transcript.
- *Rejected:* `formatException` (full traceback text), because it includes the message.

### D4. Default `LLM_TIMEOUT_SECONDS` = 60
The value is not fixed by any spec (`configuration` only requires a documented default). Eval latencies for gpt-4o-mini are 10–24 s, one case took 40 s, and Haiku took up to 60 s. 60 s per attempt keeps worst-case latency bounded (about 3 min with 2 retries) and makes spurious retries rarer.
- *Rejected:* per-profile timeouts (speculative; see proposal).

### D5. `gpt-5-chat` gets a conservative profile
`"gpt-5-chat": ModelProfile("openai", False, "none")`. Because the longest prefix wins, it overrides `gpt-5`. The profile sends no reasoning and no temperature, and a configured effort is ignored silently, like on `gpt-4o`. OpenAI documents `gpt-5-chat-latest` as a non-reasoning chat model. Whether it accepts `temperature` was not probed, since that needs a live call.

### D6. Escape the `basis` cell
`render_markdown` passes the joined `basis` through `_cell`, like the task name. `id` and `phase` are validated identifiers and enums, so they need no escaping.

## Risks / Trade-offs

- [Capping SDK loggers hides SDK debug output during local debugging] → documented in the README logging note. A scratch script without `configure_logging` still sees it.
- [A future SDK logs content at INFO] → the leak test runs at `DEBUG` through both real SDK clients with a mock transport, and would catch an INFO-level leak too.
- [`stack` exposes file paths in logs] → paths are server-side and already visible to anyone who can read the logs. No request data is included.

## Migration Plan

No migration. Deployments that set `LLM_TIMEOUT_SECONDS` explicitly keep their value. Log consumers see two new optional fields on failed `llm_call` records and one new field (`stack`) on exception records.
