# estimation-api Specification

## Purpose
Exposes the estimator over HTTP: clients submit a meeting transcription and receive an LLM-generated software estimation, either as one JSON response or as a stream of Server-Sent Events, together with the context the estimator uses, per-call metrics, health, and self-documenting API endpoints.

## Requirements

### Requirement: Estimate endpoint
The system SHALL expose `POST /api/v1/estimate` accepting a JSON body with a required `transcription` string and an optional `output_language` string, and SHALL respond `200` with a JSON body containing:
- `estimation`: the estimation rendered as markdown
- `breakdown`: the structured estimation (see `prompt-context`) enriched with computed totals
- `model` and `provider`: the model identifier and provider that served the result, after any fallback (see `llm-providers`)
- `grounding`: the grounding report (see `prompt-context`)
- `prompt_version`: the version of the prompt used
- `usage`: input, output, cached input, and cache write token counts reported by the provider
- `metrics`: the call metrics (see `Call metrics`)

The endpoint SHALL accept an optional boolean `refresh` query parameter; `refresh=true` regenerates the estimate instead of reading it from the response cache (see `response-cache`).

#### Scenario: Successful estimation
- **WHEN** a client posts `{"transcription": "<meeting text>"}` to `/api/v1/estimate`
- **THEN** the response status is `200`
- **AND** the body contains non-empty `estimation`, a `breakdown` with at least one task, and the `grounding`, `model`, `provider`, `prompt_version`, `usage`, and `metrics` fields
- **AND** `usage` contains `input_tokens`, `output_tokens`, `cached_input_tokens`, and `cache_write_tokens`

#### Scenario: Brief-compatible fields
- **WHEN** an estimation succeeds
- **THEN** the body includes `estimation` (string), `model` (string), and `provider` (string) as named in the course brief, with `provider` equal to `"openai"`, `"anthropic"`, or `"replay"` (the offline provider)

#### Scenario: Refresh documented
- **WHEN** a client reads the API contract
- **THEN** both estimate operations declare an optional boolean query parameter `refresh` that defaults to `false`

### Requirement: Request validation
The system SHALL reject invalid estimate requests with `422` before calling any LLM provider, on both estimate endpoints; on the streaming endpoint the check SHALL complete before the stream starts, so the `422` is an ordinary JSON response. A request is invalid when `transcription` is missing, empty or whitespace-only, or longer than the configured maximum length, when unknown fields are present, or when the body is not sent with a JSON content type (`Content-Type: application/json`). The JSON content-type requirement SHALL be stated in the API documentation.

#### Scenario: Empty transcription
- **WHEN** a client posts `{"transcription": "   "}`
- **THEN** the response status is `422`
- **AND** no LLM provider call is made

#### Scenario: Transcription too long
- **WHEN** a client posts a transcription longer than the configured maximum length
- **THEN** the response status is `422`

#### Scenario: Missing JSON content type
- **WHEN** a client posts a valid JSON body with `Content-Type: text/plain`
- **THEN** the response status is `422` with error code `invalid_request`
- **AND** no LLM provider call is made

### Requirement: Upstream failure mapping
The system SHALL translate LLM provider failures (the last failure, once the fallback chain in `llm-providers` has no provider left to try) into stable HTTP errors with a JSON body of the form `{"error": {"code": <string>, "message": <string>}, "request_id": <string>}` and SHALL NOT expose stack traces, provider payloads, or secrets.

| Condition | Status | `error.code` |
|---|---|---|
| Provider rate limit | 429 | `upstream_rate_limited` |
| Provider timeout, connection failure, overload, 5xx, or a stream that breaks off | 503 | `upstream_unavailable` |
| Provider refusal, truncated or schema-invalid output | 502 | `invalid_model_output` |
| Provider rejects credentials or request, or the account's quota or credits are exhausted | 502 | `upstream_error` |

#### Scenario: Provider times out
- **WHEN** the provider call times out after retries are exhausted and no fallback serves the request
- **THEN** the response status is `503` with `error.code` equal to `upstream_unavailable`

#### Scenario: Provider quota exhausted
- **WHEN** the provider reports that the account's quota or credits are exhausted
- **THEN** the response status is `502` with `error.code` equal to `upstream_error`

#### Scenario: Model output cannot be parsed
- **WHEN** the provider returns output that does not satisfy the estimation schema
- **THEN** the response status is `502` with `error.code` equal to `invalid_model_output`

### Requirement: Request correlation
The system SHALL attach a request identifier to every response in the `X-Request-ID` header, reusing a client-supplied `X-Request-ID` when it is 1 to 128 characters of letters, digits, `.`, `_`, `:`, or `-`, and generating one otherwise, and SHALL include it in error bodies, stream `error` events, and logs.

#### Scenario: Client supplies request id
- **WHEN** a request carries `X-Request-ID: abc-123`
- **THEN** the response carries `X-Request-ID: abc-123`

#### Scenario: Unsafe request id replaced
- **WHEN** a request carries an `X-Request-ID` of 500 characters
- **THEN** the response carries a generated request id instead

### Requirement: Host allowlist
The system SHALL answer only requests whose `Host` header names one of the configured allowed hosts (`ALLOWED_HOSTS`, see `configuration`), comparing the name without its port and ignoring case, so that a web page which rebinds its own name to the loopback address (DNS rebinding) cannot call the loopback-published API from a browser. Any other request, including one without a `Host` header, SHALL be answered `400` with error code `invalid_host` and the request id, before any handler runs and without calling any LLM provider. The default allowed hosts SHALL cover the loopback names `localhost` and `127.0.0.1` (the Compose healthcheck, `make run` and `make dev`), the Compose service name `ai-service` (the BFF's upstream), and the test client's `testserver`.

#### Scenario: Rebound host rejected
- **WHEN** a client posts a valid transcription to `/api/v1/estimate/stream?refresh=true` with `Host: rebind.attacker.example:8000`
- **THEN** the response status is `400` with error code `invalid_host` and the request id
- **AND** no LLM provider call is made

#### Scenario: Loopback and Compose callers answered
- **WHEN** a client calls `GET /health` with `Host: 127.0.0.1:8000`, `localhost:8000`, or `ai-service:8000`
- **THEN** the response status is `200`

### Requirement: Health endpoint
The system SHALL expose `GET /health` returning `200` with `status`, application `version`, `environment`, the primary `provider` and `model`, and the configured provider `chain` (`provider:model` entries, primary first), without calling any LLM provider.

#### Scenario: Service is up
- **WHEN** a client calls `GET /health`
- **THEN** the response status is `200` and `status` equals `"ok"`
- **AND** no LLM provider is called

#### Scenario: Chain reported
- **WHEN** the service runs with `LLM_PROVIDER=replay` and `LLM_FALLBACKS=none`
- **THEN** `GET /health` reports provider `replay`, model `replay`, and chain `["replay:replay"]`

### Requirement: API documentation
The system SHALL serve interactive OpenAPI documentation at `/docs` with a descriptive title and description, including request and response examples for the estimate endpoint.

#### Scenario: Docs available
- **WHEN** a client requests `GET /docs`
- **THEN** the response status is `200`

### Requirement: Unexpected errors
The system SHALL answer any unexpected server error, raised before the response has started, with `500` and the JSON body `{"error": {"code": "internal_error", "message": "Internal server error."}, "request_id": <string>}`, carrying the request id in the `X-Request-ID` header. It SHALL log one record with the request id, the exception type, and the stack locations (file, line, and function of each frame), and SHALL NOT include the exception message in the response or the log record, because messages can echo request data.

#### Scenario: Unexpected error answered and logged
- **WHEN** a handler raises an unexpected exception whose message contains request data
- **THEN** the response status is `500` with error code `internal_error` and the request id
- **AND** the log record contains the exception type and the raising function's stack location
- **AND** neither the response nor the log record contains the exception message

### Requirement: Streaming estimate endpoint
The system SHALL expose `POST /api/v1/estimate/stream`, which accepts the same body and `refresh` parameter as `POST /api/v1/estimate` and responds `200` with `text/event-stream`. The stream SHALL carry these events, whose payload schemas SHALL be part of the API contract:

| Event | Data | Rules |
|---|---|---|
| `status` | `{phase, provider, model}`, with `phase` one of `calling_llm`, `fallback`, `validating`, `cache_hit` | Informational |
| `partial` | `{seq, breakdown}`: the estimation parsed from the model output received so far, possibly incomplete | Only after the first model output, only when the parsed snapshot changed, at most one per 100 ms plus one final flush before the terminal event; `seq` strictly increasing and also sent as the event `id` |
| `result` | the same body as `POST /api/v1/estimate` | Terminal |
| `error` | `{code, message, retryable, request_id}` | Terminal |

A stream that calls a provider SHALL start with `status` `calling_llm` naming the primary provider, SHALL send `status` `fallback` naming the next provider before any output from it, and SHALL send `status` `validating` before `result`. A response served from the response cache SHALL stream `status` `cache_hit` followed by `result`. Every stream SHALL end with exactly one terminal event. A failure after the stream has started SHALL be sent as an `error` event whose `code` follows `Upstream failure mapping` (`internal_error` for an unexpected failure), with `retryable` true only for `upstream_rate_limited` and `upstream_unavailable`. Model output that cannot be parsed yet SHALL produce no `partial` event and SHALL NOT end the stream. The response SHALL disable proxy buffering (`X-Accel-Buffering: no`) and SHALL send a keep-alive comment every 15 s while idle. When the client disconnects, including a client that stopped reading, the system SHALL close the upstream provider stream promptly, log the call with outcome `cancelled` and the request's id, and store nothing in the response cache.

#### Scenario: Streamed estimate
- **WHEN** a client posts a valid transcription to `/api/v1/estimate/stream`
- **THEN** the response status is `200` with content type `text/event-stream` and `X-Accel-Buffering: no`
- **AND** the first event is `status`, at least one `partial` event follows, and the last event is `result`
- **AND** the stream contains exactly one terminal event

#### Scenario: Invalid request answered before the stream
- **WHEN** a client posts a transcription longer than the configured maximum length to `/api/v1/estimate/stream`
- **THEN** the response status is `422` with a JSON body whose error code is `invalid_request`
- **AND** no LLM provider call is made

#### Scenario: Failure after the stream started
- **WHEN** the provider is unavailable during a streamed request
- **THEN** the last event is `error` with code `upstream_unavailable`, `retryable` true, and the `request_id` of the response's `X-Request-ID`

#### Scenario: Unparseable partial output
- **WHEN** the model output received so far is empty, malformed, or not a JSON object
- **THEN** no `partial` event is sent for it and the stream still ends with exactly one `result`

#### Scenario: Fallback announced
- **WHEN** the primary provider is unavailable before its first output and the fallback serves the request
- **THEN** the stream sends `status` `calling_llm` naming the primary, then `status` `fallback` naming the fallback provider and model
- **AND** the `result` reports the fallback's provider and model, `metrics.fallback_used` true, and `metrics.attempts` 2

#### Scenario: Client disconnects mid-stream
- **WHEN** a client disconnects after receiving a `partial` event, or stops reading and then disconnects
- **THEN** the upstream provider stream is closed within one second
- **AND** one `llm_call` record with outcome `cancelled` and the request's id is logged
- **AND** nothing is stored in the response cache

### Requirement: Call metrics
Every estimate response, from either endpoint, SHALL carry `metrics` with:
- `latency_ms`: end to end, from the first provider attempt to the served result, failed attempts included
- `ttft_ms`: on streamed calls, the time from the first provider attempt to the first model output; null on blocking calls
- `cost_usd`: the USD cost computed in code from the reported usage and a dated table of per-model prices per million tokens (uncached input, cached input, cache write, output); null when the model has no price
- `cache_hit`: whether the response came from the response cache
- `fallback_used`: whether a provider other than the primary served it
- `attempts`: the number of provider calls made for it

A response served from the response cache SHALL report the metrics of the lookup, as specified in `response-cache`.

#### Scenario: Blocking call metrics
- **WHEN** a blocking estimation is served by the primary provider
- **THEN** `metrics.cache_hit` is false, `metrics.attempts` is 1, and `metrics.ttft_ms` is null

#### Scenario: Metrics after a fallback are end to end
- **WHEN** a streamed estimation is served by the fallback after the primary failed
- **THEN** `metrics.latency_ms` includes the failed attempt and `metrics.ttft_ms` is lower than `metrics.latency_ms`

#### Scenario: Cached input billed at the cached rate
- **WHEN** a `gpt-4o-mini` call reports 10,000 input tokens, 8,000 of them cached, and 1,000 output tokens
- **THEN** its cost is US$0.0015

#### Scenario: Unpriced model
- **WHEN** the serving model has no price entry
- **THEN** `metrics.cost_usd` is null

### Requirement: Context endpoint
The system SHALL expose `GET /api/v1/context` returning, without calling any LLM provider: `prompt_version`; `system_prompt`, the exact system prompt sent to the provider; `references`, each reference estimation in that prompt with its `size`, `meeting_summary`, and `estimation`; `chain`, the configured providers as `provider:model`, primary first; and `max_transcription_chars`, the configured maximum transcription length.

#### Scenario: Prompt and references exposed
- **WHEN** a client calls `GET /api/v1/context`
- **THEN** the body contains the prompt version, a system prompt that includes the reference estimations, three references, and a non-empty chain

#### Scenario: Chain and limit reported
- **WHEN** the service runs with a maximum transcription length of 10 and no fallback
- **THEN** `GET /api/v1/context` reports `max_transcription_chars` 10 and chain `["openai:gpt-4o-mini"]`
- **AND** no LLM provider is called
