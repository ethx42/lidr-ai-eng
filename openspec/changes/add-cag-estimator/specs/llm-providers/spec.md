## Purpose

Generates a schema-conformant structured estimation from a prompt through a pluggable LLM provider, so the rest of the system is independent of which vendor serves the request.

## ADDED Requirements

### Requirement: Provider selection
The system SHALL support `openai` and `anthropic` as providers, selected by the `LLM_PROVIDER` setting, using the model named by `LLM_MODEL`. Adding a provider SHALL NOT require changes to the HTTP layer or the estimation logic.

#### Scenario: Anthropic selected
- **WHEN** `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-haiku-4-5`
- **THEN** estimation requests are served by Anthropic with that model and the response reports `provider: "anthropic"`

### Requirement: Model request profiles
The system SHALL shape every provider request according to a profile of the configured model's capabilities, so each model receives only parameters it supports:
- sampling parameters (temperature) SHALL be sent only to models that accept them
- reasoning or thinking effort SHALL be sent, in the provider's native form, only to models that support it and only when configured
- the output token budget SHALL leave room for reasoning tokens on reasoning models

A model without a known profile SHALL use a conservative profile (no sampling and no reasoning parameters), and the system SHALL log a warning at startup naming the model.

#### Scenario: Non-reasoning OpenAI model
- **WHEN** the model is `gpt-4o-mini` and a temperature is configured
- **THEN** the request includes the temperature and no reasoning parameters

#### Scenario: OpenAI reasoning model
- **WHEN** the model belongs to the gpt-5 family and a reasoning effort is configured
- **THEN** the request includes the reasoning effort and no temperature

#### Scenario: Claude model without sampling parameters
- **WHEN** the model is `claude-opus-5` and a temperature is configured
- **THEN** the request includes no temperature

#### Scenario: Unknown model
- **WHEN** the model is `acme-llm-1`
- **THEN** the request includes neither temperature nor reasoning parameters
- **AND** a startup warning names `acme-llm-1`

### Requirement: Structured output enforcement
The system SHALL request output constrained to the estimation schema using each provider's native structured-output mechanism and SHALL validate the result against the schema before use. Free-text parsing of model output SHALL NOT be used.

#### Scenario: Valid structured output
- **WHEN** the provider returns output matching the schema
- **THEN** the system receives a fully validated estimation object

#### Scenario: Refusal or truncation
- **WHEN** the provider refuses, stops because of the output token limit, or returns no parseable object
- **THEN** the system raises an invalid-output failure (mapped to `502` by `estimation-api`)

### Requirement: Bounded latency and retries
Every provider call SHALL use the configured request timeout and a bounded number of retries for transient failures (rate limits, timeouts, connection errors, 5xx). Non-transient failures SHALL NOT be retried.

#### Scenario: Transient failure then success
- **WHEN** the first provider attempt fails with a transient error and a retry succeeds
- **THEN** the estimation is returned successfully

### Requirement: Usage and telemetry
Each provider call SHALL report input tokens, output tokens, cached input tokens (0 when unavailable), and latency, and SHALL emit one structured log record per call containing provider, model, prompt version, token counts, latency, outcome, and request id, but never the transcription text or API keys.

#### Scenario: Call logged without content
- **WHEN** an estimation completes
- **THEN** a log record exists with token counts and latency
- **AND** the record does not contain the transcription text

### Requirement: Client lifecycle
Provider clients SHALL be created once at application startup and closed at shutdown, not per request.

#### Scenario: Reused client
- **WHEN** two estimation requests are served
- **THEN** both use the same provider client instance
