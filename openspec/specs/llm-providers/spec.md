# llm-providers Specification

## Purpose
Generates a schema-conformant structured estimation from a prompt through a pluggable LLM provider, so the rest of the system is independent of which vendor serves the request.

## Requirements

### Requirement: Provider selection
The system SHALL support `openai` and `anthropic` as providers, selected by the `LLM_PROVIDER` setting, using the model named by `LLM_MODEL`. Adding a provider SHALL NOT require changes to the HTTP layer or the estimation logic.

#### Scenario: Anthropic selected
- **WHEN** `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-haiku-4-5`
- **THEN** estimation requests are served by Anthropic with that model and the response reports `provider: "anthropic"`

### Requirement: Model request profiles
The system SHALL shape every provider request according to a profile of the configured model's capabilities, so each model receives only parameters it supports:
- sampling parameters (temperature) SHALL be sent only to models that accept them
- reasoning or thinking effort SHALL be sent, in the provider's native form, only to models that support reasoning, only when configured, and only when the model supports the configured level
- the output token budget SHALL leave room for reasoning tokens on reasoning models

When the configured effort level is not supported by a reasoning model, the system SHALL send no effort for that model and SHALL log a warning at startup naming the model, the configured level, and the levels the model supports.

A model without a known profile SHALL use a conservative profile (no sampling and no reasoning parameters), and the system SHALL log a warning at startup naming the model.

#### Scenario: Non-reasoning OpenAI model
- **WHEN** the model is `gpt-4o-mini` and a temperature is configured
- **THEN** the request includes the temperature and no reasoning parameters

#### Scenario: OpenAI reasoning model
- **WHEN** the model belongs to the gpt-5 family and a reasoning effort it supports is configured
- **THEN** the request includes the reasoning effort and no temperature

#### Scenario: Extended effort level on a model that supports it
- **WHEN** the model is `claude-opus-5` and the reasoning effort is `max`
- **THEN** the request includes effort `max` in the provider's native form

#### Scenario: Effort level the model does not support
- **WHEN** the model is `claude-opus-5` and the reasoning effort is `minimal`
- **THEN** the request includes no effort and no thinking parameters
- **AND** a startup warning names `claude-opus-5`, `minimal`, and the supported levels

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

#### Scenario: Context window exhausted
- **WHEN** the provider reports that generation stopped because the model's context window was exhausted
- **THEN** the system raises an invalid-output failure, even if a parseable object was returned

### Requirement: Bounded latency and retries
Every provider call SHALL use the configured request timeout and a bounded number of retries for transient failures (rate limits, timeouts, connection errors, 5xx). Non-transient failures SHALL NOT be retried, including rejected credentials or requests and exhausted quota or credits, even when the provider signals them with a rate-limit status.

#### Scenario: Transient failure then success
- **WHEN** the first provider attempt fails with a transient error and a retry succeeds
- **THEN** the estimation is returned successfully

#### Scenario: Quota exhausted is not retried
- **WHEN** the provider reports exhausted quota or credits
- **THEN** exactly one attempt is made and an upstream-error failure is raised

### Requirement: Usage and telemetry
Each provider call SHALL report input tokens, output tokens, cached input tokens (tokens read from the prompt cache), cache write tokens (tokens written to the prompt cache), and latency, with 0 for any count the provider does not report. Input tokens SHALL be the total across cached and uncached input. Each call SHALL emit one structured log record containing provider, model, prompt version, all token counts, latency, outcome, and request id, but never the transcription text or API keys. When a call fails, its record SHALL also contain the cause (the upstream error class, or the stop condition that made the output invalid) and the upstream HTTP status when there is one, but never the provider's error message or response body. No log record emitted while serving a request, by the application or by the libraries it uses, SHALL contain the transcription text, at any configured log level.

#### Scenario: Call logged without content
- **WHEN** an estimation completes
- **THEN** a log record exists with token counts, including cached input and cache write tokens, and latency
- **AND** the record does not contain the transcription text

#### Scenario: Cache write reported
- **WHEN** the provider reports that part of the prompt was written to its cache
- **THEN** the call's usage reports that count as cache write tokens

#### Scenario: Debug logging leaks no content
- **WHEN** the log level is `DEBUG` and an estimation request is sent to either provider
- **THEN** no captured log record, from any logger, contains the transcription text

#### Scenario: Upstream rejection logged with its cause
- **WHEN** the provider rejects a call with HTTP `400` and an error message
- **THEN** the call's log record has outcome `upstream_error`, upstream status `400`, and the upstream error class as cause
- **AND** the record does not contain the provider's error message

#### Scenario: Truncated output logged with its stop condition
- **WHEN** the provider stops generating because of the output token limit
- **THEN** the call's log record has outcome `invalid_model_output` and a cause naming the token-limit stop condition

### Requirement: Client lifecycle
Provider clients SHALL be created once at application startup and closed at shutdown, not per request.

#### Scenario: Reused client
- **WHEN** two estimation requests are served
- **THEN** both use the same provider client instance

### Requirement: Prompt cache routing
On providers that accept a prompt-cache routing key, every request SHALL carry a key derived only from the prompt version, so requests sharing the byte-stable system prompt are routed to the same cache. The key SHALL contain no per-request or user data.

#### Scenario: Same key across requests
- **WHEN** two estimation requests are served by OpenAI with the same prompt version
- **THEN** both requests carry the same cache routing key, which includes the prompt version

#### Scenario: Key changes with prompt version
- **WHEN** the prompt version changes
- **THEN** the cache routing key changes
