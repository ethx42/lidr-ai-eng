## Why

The M1 review of PR #1 found that at the default `LOG_LEVEL=DEBUG` the Anthropic SDK logs every request body, so each client transcription (and the full system prompt) lands in the application logs. That breaks the `llm-providers` telemetry requirement and the design's "transcription text is never logged". The same review found that failures are hard to diagnose: a failed provider call logs only `outcome=upstream_error` with no cause, and unhandled errors log only the exception type. A few smaller gaps (a tight default timeout, a model family that would receive rejected parameters, an unescaped markdown cell, and stale or broken docs) are cheap to close before M1 is merged and tagged.

## What Changes

- **No request content in logs at any level**: third-party client loggers are capped so that no log record, at any configured level, contains the transcription. `LOG_LEVEL=DEBUG` stays the default (course brief).
- **Failure cause in the `llm_call` record**: a failed call records what caused it, meaning the upstream error class or the stop condition (e.g. output truncated at the token limit), plus the upstream HTTP status when there is one. The provider's error body and message are never logged.
- **Unhandled errors keep their stack**: the unhandled-error log record carries the stack locations (file, line, function) besides the exception type. The exception message is still omitted, because messages can echo request data.
- **Default request timeout 30 → 60 seconds**: measured gpt-4o-mini calls already take 10–24 s and one eval case (40 s) needed a retry. Documented in the README and `.env.example`.
- **`gpt-5-chat` profile**: the `gpt-5-chat*` models no longer inherit the `gpt-5` reasoning profile. They get a conservative profile with no reasoning and no sampling parameters.
- **Markdown table escaping**: every free-text cell in the task table is escaped, including `basis`.
- **Docs**: commit the eval report the README cites, fix the `LLM_REASONING_EFFORT` comment in `.env.example`, and update `.claude/stack.md` (stale branch reference, and the Anthropic SDK DEBUG logging behavior).

No breaking changes. The API contract is unchanged. The `llm_call` log record gains two fields on failures.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `llm-providers`: telemetry now forbids request content in any log record at any level, and failed calls record their cause and upstream status.
- `estimation-api`: unexpected errors are specified: a JSON `500` carrying the request id, and a log record with the exception type and stack locations but no exception message.

## Impact

- Code: `app/observability.py`, `app/services/errors.py`, `app/services/llm_service.py`, `app/services/providers/{openai,anthropic}_provider.py` (stop-condition reasons), `profiles.py`, `app/services/rendering.py`, `app/config.py` (timeout default), `app/main.py` (unhandled-error record), tests.
- Docs and config: `README.md`, `.env.example`, `.claude/stack.md`, `evals/reports/v4-20260923T145152Z.json` (force-added).
- No new dependencies. No prompt change (prompt version stays `v4`), so no live eval is needed.

## Explicitly deferred

- **Minimum evidence length for grounding**: a one-word quote currently counts as grounded. Tightening it changes the grounding contract and makes scores incomparable with the v4 baseline, so it belongs in M2 with a new baseline.
- **Per-model timeouts**: one documented default is enough until a reasoning model is the configured default.
- **Live probe of `gpt-5-chat` parameters**: the conservative profile is safe without it. Enabling temperature later needs a live call, which requires the user's approval.
- **CI running twice on PR branches** (`push` + `pull_request`): costs CI minutes only.
