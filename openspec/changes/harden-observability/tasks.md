# Tasks

## 1. No request content in logs (`fix(observability):` commit)

- [x] 1.1 Add a failing test in `tests/unit/providers/test_retries.py` (real SDK clients, `httpx2.MockTransport`), parametrized over both providers: after `configure_logging("DEBUG")`, a `generate` call with a unique transcript marker leaves no captured record from any logger containing the marker. Verify it fails for Anthropic
- [x] 1.2 Implement D1 (`CLIENT_LOGGERS` capped at `max(level, INFO)` in `configure_logging`). Verify the 1.1 test passes for both providers, an `app.*` DEBUG record is still emitted at `LOG_LEVEL=DEBUG`, and `make check` exits 0

## 2. Failure causes and unhandled-error stacks (`feat(observability):` commit)

- [x] 2.1 Add failing tests: `LLMError` exposes `cause`/`upstream_status` from a chained exception and prefers an explicit `reason`. An Anthropic `400` (mock transport, error message `"secret upstream detail"`) produces an `llm_call` record with `outcome=upstream_error`, `upstream_status=400`, `cause=BadRequestError`, and no `"secret upstream detail"`. An Anthropic `stop_reason: "max_tokens"` and an OpenAI `incomplete` / `max_output_tokens` response, each with *truncated JSON text* (mock transport), log `cause` `stop_reason:max_tokens` / `incomplete:max_output_tokens`. An Anthropic request body's `output_config.format` equals what `messages.parse` sends for the same schema. Successful records carry neither field
- [x] 2.2 Implement D2 (`reason` keyword and the properties on `LLMError`; OpenAI `with_raw_response.parse` and Anthropic `create` + `transform_schema` reading the stop condition before parsing; the optional fields in `log_llm_call`; the service wiring). Move the stubbed provider unit tests to the new client calls. Verify the 2.1 tests and all existing provider tests pass
- [x] 2.3 Extend `test_unhandled_error_returns_json_500_with_request_id`: the captured `unhandled_error` record, formatted by `JsonFormatter`, has `exc_type == "RuntimeError"`, a `stack` entry naming `explode`, and no `"secret internals"`. Implement D3. Verify the test passes and `make check` exits 0

## 3. Reliability defaults (`fix:` commit)

- [x] 3.1 Add failing tests: the default `llm_timeout_seconds` is `60`. `gpt-5-chat-latest` with effort `low` and temperature `0.2` gets no `reasoning`, no `temperature`, and `max_output_tokens` without reasoning headroom. A task whose `basis` contains `|` renders as one table row with the pipe escaped
- [x] 3.2 Implement D4–D6 (config default, `gpt-5-chat` profile, `_cell` on the basis cell). Verify the 3.1 tests pass and `make check` exits 0

## 4. Docs (`docs:` commit)

- [x] 4.1 `git add -f evals/reports/v4-20260923T145152Z.json`. Verify every `evals/reports/*.json` link in `README.md` resolves to a tracked file (`git ls-files`)
- [ ] 4.2 README: timeout default `60`, and a logging note (client libraries are capped at INFO, so no request content is logged; failed `llm_call` records carry `cause` and `upstream_status`). `.env.example`: `LLM_TIMEOUT_SECONDS=60`, and the effort comment lists `none|minimal|low|medium|high|xhigh|max`, supported per model. Verify by reading the diff
- [x] 4.3 `.claude/stack.md`: Anthropic "Avoid" gains the DEBUG request-body logging behaviour. The findings section drops the stale branch reference and records this change. Verify `make check` exits 0

## 5. Verify and archive (`chore(openspec):` commit)

- [ ] 5.1 Run `/opsx:verify` for `harden-observability`. Verify it reports no gaps
- [ ] 5.2 Archive the change into `openspec/specs/`. Verify `make specs` passes and the main `llm-providers` and `estimation-api` specs contain the new scenarios
