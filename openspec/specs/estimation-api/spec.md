# estimation-api Specification

## Purpose
Exposes the estimator over HTTP: clients submit a meeting transcription and receive an LLM-generated software estimation, with health and self-documenting API endpoints.

## Requirements

### Requirement: Estimate endpoint
The system SHALL expose `POST /api/v1/estimate` accepting a JSON body with a required `transcription` string and an optional `output_language` string, and SHALL respond `200` with a JSON body containing:
- `estimation`: the estimation rendered as markdown
- `breakdown`: the structured estimation (see `prompt-context`) enriched with computed totals
- `model` and `provider`: the model identifier and provider that produced it
- `grounding`: the grounding report (see `prompt-context`)
- `prompt_version`: the version of the prompt used
- `usage`: input, output, cached input, and cache write token counts reported by the provider

#### Scenario: Successful estimation
- **WHEN** a client posts `{"transcription": "<meeting text>"}` to `/api/v1/estimate`
- **THEN** the response status is `200`
- **AND** the body contains non-empty `estimation`, a `breakdown` with at least one task, and the `grounding`, `model`, `provider`, `prompt_version`, and `usage` fields
- **AND** `usage` contains `input_tokens`, `output_tokens`, `cached_input_tokens`, and `cache_write_tokens`

#### Scenario: Brief-compatible fields
- **WHEN** an estimation succeeds
- **THEN** the body includes `estimation` (string), `model` (string), and `provider` (`"openai"` or `"anthropic"`) exactly as named in the course brief

### Requirement: Request validation
The system SHALL reject invalid estimate requests with `422` before calling any LLM provider. A request is invalid when `transcription` is missing, empty or whitespace-only, or longer than the configured maximum length, when unknown fields are present, or when the body is not sent with a JSON content type (`Content-Type: application/json`). The JSON content-type requirement SHALL be stated in the API documentation.

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
The system SHALL translate LLM provider failures into stable HTTP errors with a JSON body of the form `{"error": {"code": <string>, "message": <string>}, "request_id": <string>}` and SHALL NOT expose stack traces, provider payloads, or secrets.

| Condition | Status | `error.code` |
|---|---|---|
| Provider rate limit | 429 | `upstream_rate_limited` |
| Provider timeout, connection failure, or 5xx | 503 | `upstream_unavailable` |
| Provider refusal, truncated or schema-invalid output | 502 | `invalid_model_output` |
| Provider rejects credentials or request, or the account's quota or credits are exhausted | 502 | `upstream_error` |

#### Scenario: Provider times out
- **WHEN** the provider call times out after retries are exhausted
- **THEN** the response status is `503` with `error.code` equal to `upstream_unavailable`

#### Scenario: Provider quota exhausted
- **WHEN** the provider reports that the account's quota or credits are exhausted
- **THEN** the response status is `502` with `error.code` equal to `upstream_error`

#### Scenario: Model output cannot be parsed
- **WHEN** the provider returns output that does not satisfy the estimation schema
- **THEN** the response status is `502` with `error.code` equal to `invalid_model_output`

### Requirement: Request correlation
The system SHALL attach a request identifier to every response in the `X-Request-ID` header, reusing a client-supplied `X-Request-ID` when present, and SHALL include it in error bodies and logs.

#### Scenario: Client supplies request id
- **WHEN** a request carries `X-Request-ID: abc-123`
- **THEN** the response carries `X-Request-ID: abc-123`

### Requirement: Health endpoint
The system SHALL expose `GET /health` returning `200` with `status`, application `version`, `environment`, configured `provider`, and `model`, without calling any LLM provider.

#### Scenario: Service is up
- **WHEN** a client calls `GET /health`
- **THEN** the response status is `200` and `status` equals `"ok"`

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
