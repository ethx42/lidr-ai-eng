## MODIFIED Requirements

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
