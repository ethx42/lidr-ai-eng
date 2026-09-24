## MODIFIED Requirements

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
