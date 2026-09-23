## Purpose

Exposes the estimator over HTTP: clients submit a meeting transcription and receive an LLM-generated software estimation, with health and self-documenting API endpoints.

## ADDED Requirements

### Requirement: Estimate endpoint
The system SHALL expose `POST /api/v1/estimate` accepting a JSON body with a required `transcription` string and an optional `output_language` string, and SHALL respond `200` with a JSON body containing:
- `estimation`: the estimation rendered as markdown
- `breakdown`: the structured estimation (see `prompt-context`) enriched with computed totals
- `model` and `provider`: the model identifier and provider that produced it
- `grounding`: the grounding report (see `prompt-context`)
- `prompt_version`: the version of the prompt used
- `usage`: input, output, and cached input token counts reported by the provider

#### Scenario: Successful estimation
- **WHEN** a client posts `{"transcription": "<meeting text>"}` to `/api/v1/estimate`
- **THEN** the response status is `200`
- **AND** the body contains non-empty `estimation`, a `breakdown` with at least one task, and the `grounding`, `model`, `provider`, `prompt_version`, and `usage` fields

#### Scenario: Brief-compatible fields
- **WHEN** an estimation succeeds
- **THEN** the body includes `estimation` (string), `model` (string), and `provider` (`"openai"` or `"anthropic"`) exactly as named in the course brief

### Requirement: Request validation
The system SHALL reject invalid estimate requests with `422` before calling any LLM provider. A request is invalid when `transcription` is missing, empty or whitespace-only, or longer than the configured maximum length, or when unknown fields are present.

#### Scenario: Empty transcription
- **WHEN** a client posts `{"transcription": "   "}`
- **THEN** the response status is `422`
- **AND** no LLM provider call is made

#### Scenario: Transcription too long
- **WHEN** a client posts a transcription longer than the configured maximum length
- **THEN** the response status is `422`

### Requirement: Upstream failure mapping
The system SHALL translate LLM provider failures into stable HTTP errors with a JSON body of the form `{"error": {"code": <string>, "message": <string>}, "request_id": <string>}` and SHALL NOT expose stack traces, provider payloads, or secrets.

| Condition | Status | `error.code` |
|---|---|---|
| Provider rate limit | 429 | `upstream_rate_limited` |
| Provider timeout, connection failure, or 5xx | 503 | `upstream_unavailable` |
| Provider refusal, truncated or schema-invalid output | 502 | `invalid_model_output` |
| Provider rejects credentials or request | 502 | `upstream_error` |

#### Scenario: Provider times out
- **WHEN** the provider call times out after retries are exhausted
- **THEN** the response status is `503` with `error.code` equal to `upstream_unavailable`

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
