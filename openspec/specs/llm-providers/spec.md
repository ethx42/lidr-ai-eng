# llm-providers Specification

## Purpose
Generates a schema-conformant structured estimation from a prompt, blocking or streamed, through a chain of pluggable LLM providers behind a fallback router, so the rest of the system is independent of which vendor serves the request; an offline replay provider serves recorded streams for tests and demos.

## Requirements

### Requirement: Provider selection
The system SHALL support `openai`, `anthropic`, and `replay` (see `Replay provider`) as providers. `LLM_PROVIDER` and `LLM_MODEL` SHALL select the primary provider, and `LLM_FALLBACKS` the providers tried after it (see `Fallback router`). Adding a provider SHALL NOT require changes to the HTTP layer or the estimation logic.

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
The system SHALL request output constrained to the estimation schema using each provider's native structured-output mechanism and SHALL validate the result against the schema before use. Free-text parsing of model output SHALL NOT be used. A provider SHALL read the stop condition before validating, so output cut off by the token limit or the context window is reported with that stop condition, on blocking and streamed calls alike.

#### Scenario: Valid structured output
- **WHEN** the provider returns output matching the schema
- **THEN** the system receives a fully validated estimation object

#### Scenario: Refusal or truncation
- **WHEN** the provider refuses, stops because of the output token limit, or returns no parseable object
- **THEN** the system raises an invalid-output failure (mapped to `502` by `estimation-api`)

#### Scenario: Context window exhausted
- **WHEN** the provider reports that generation stopped because the model's context window was exhausted
- **THEN** the system raises an invalid-output failure, even if a parseable object was returned

#### Scenario: Streamed output truncated
- **WHEN** a streamed response stops because of the output token limit
- **THEN** the text deltas received so far are delivered
- **AND** the stream ends with an invalid-output failure whose cause names the token-limit stop condition

### Requirement: Bounded latency and retries
Every provider call SHALL use the configured request timeout. Only the last provider in the chain SHALL retry transient failures (rate limits, timeouts, connection errors, 5xx) itself, up to `LLM_MAX_RETRIES` times; every provider before it SHALL make a single attempt, because the router's next provider is its retry. Non-transient failures SHALL NOT be retried, including rejected credentials or requests and exhausted quota or credits, even when the provider signals them with a rate-limit status.

#### Scenario: Transient failure then success
- **WHEN** the first attempt of the last provider in the chain fails with a transient error and a retry succeeds
- **THEN** the estimation is returned successfully

#### Scenario: Only the last provider retries
- **WHEN** the chain has three providers and `LLM_MAX_RETRIES=3`
- **THEN** the first two providers make no retries and the last one retries up to 3 times

#### Scenario: Quota exhausted is not retried
- **WHEN** the provider reports exhausted quota or credits
- **THEN** exactly one attempt is made on that provider and an upstream-error failure marked as exhausted quota is raised

### Requirement: Usage and telemetry
Each provider call SHALL report input tokens, output tokens, cached input tokens (tokens read from the prompt cache), cache write tokens (tokens written to the prompt cache), and latency, with 0 for any count the provider does not report. Input tokens SHALL be the total across cached and uncached input. The call that serves a request, fails last, or is cancelled SHALL emit one `llm_call` log record containing provider, model, prompt version, all token counts, latency, time to first output (streamed calls), cost in USD, whether it streamed, the attempt number, whether it was a fallback, the response-cache status (`hit`, `miss`, `error`, or `bypass`), outcome (`ok`, `cancelled`, or the error code), and request id, but never the transcription text or API keys. Each failed attempt that the router moves past SHALL instead emit one `llm_fallback` warning with the same identifying fields, that attempt's own latency, its outcome, and its cause. When a call fails, its record SHALL also contain the cause (the upstream error class, or the stop condition that made the output invalid) and the upstream HTTP status when there is one, but never the provider's error message or response body. No log record emitted while serving a request, by the application or by the libraries it uses, SHALL contain the transcription text, at any configured log level.

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

#### Scenario: One record per attempt after a fallback
- **WHEN** the primary is unavailable and the fallback serves the request
- **THEN** one `llm_fallback` record names the primary as attempt 1 with outcome `upstream_unavailable`
- **AND** one `llm_call` record names the fallback as attempt 2, marked as a fallback, with outcome `ok`

#### Scenario: Cancelled stream logged with the provider in flight
- **WHEN** the client leaves a streamed request while the fallback is streaming
- **THEN** one `llm_call` record names the fallback provider and model, attempt 2, with outcome `cancelled`

### Requirement: Client lifecycle
Provider clients SHALL be created once at application startup and closed at shutdown, not per request. Shutdown SHALL close every provider in the chain, even when closing one of them fails.

#### Scenario: Reused client
- **WHEN** two estimation requests are served
- **THEN** both use the same provider client instance

#### Scenario: Every provider closed
- **WHEN** the router is closed and closing one provider in the chain fails
- **THEN** every other provider is still closed and the failure is raised afterwards

### Requirement: Prompt cache routing
On providers that accept a prompt-cache routing key, every request SHALL carry a key derived only from the version that rendered its prompt (`estimator-<version>`), so requests of one version, whose system prompts share the long static prefix that ends before the output-format and detail-level blocks (see `Cache-stable prompt prefix` in `prompt-context`), are routed to the same cache whatever their choices. The key SHALL contain no per-request or user data. On providers that cache by marked content instead, the system prompt SHALL be sent as its own block marked for caching.

#### Scenario: Same key across requests
- **WHEN** two estimation requests are served by OpenAI with the same prompt version
- **THEN** both requests carry the same cache routing key, which includes the prompt version

#### Scenario: Key changes with prompt version
- **WHEN** one request is rendered from `v2` and another from `v1`
- **THEN** they carry the routing keys `estimator-v2` and `estimator-v1`

#### Scenario: Choices do not change the key
- **WHEN** two requests of the same prompt version differ in project type, detail level, and output format
- **THEN** both carry the same cache routing key

#### Scenario: Anthropic system prompt marked for caching
- **WHEN** an estimation is served by Anthropic
- **THEN** the system prompt is sent as one text block with an ephemeral cache-control marker, followed by one user message

#### Scenario: Streamed and blocking calls share the key
- **WHEN** one blocking and one streamed estimation are served with the same prompt version
- **THEN** both provider calls carry the same cache routing key

### Requirement: Streaming generation
Every provider SHALL offer a streaming call that yields the model's text deltas in order, each with the text accumulated so far, followed by exactly one validated result carrying usage, latency, provider, and model. Streamed failures SHALL map to the same failure kinds as blocking calls, including errors reported inside a successful HTTP stream, which SHALL be classified by their error code or type. A transport failure while reading the stream, events out of the provider's protocol order, and a stream that ends without its terminal event SHALL be unavailable failures. Closing the stream early SHALL close the upstream HTTP response.

#### Scenario: Completed stream
- **WHEN** the provider streams a complete, schema-valid answer
- **THEN** the call yields text deltas whose concatenation is the answer, then one result with the parsed estimation and the reported usage

#### Scenario: Error event inside the stream
- **WHEN** an Anthropic stream carries an `overloaded_error` event after some text
- **THEN** the call raises an unavailable failure after the text deltas already yielded
- **AND** a `rate_limit_error` event raises a rate-limited failure instead

#### Scenario: Stream ends without its terminal event
- **WHEN** the provider's stream ends before its completion event
- **THEN** the call raises an unavailable failure with cause `no_terminal_event`

#### Scenario: Events out of order
- **WHEN** the provider sends an event before the one that opens the response
- **THEN** the call raises an unavailable failure with cause `stream_protocol`

#### Scenario: Stream closed early
- **WHEN** the caller closes the stream after the first text delta
- **THEN** the upstream HTTP response is closed

### Requirement: Fallback router
Every provider call SHALL go through a router over the configured chain, even when the chain has one provider. The router SHALL try providers in chain order and SHALL move to the next one only after an availability failure: the provider is unavailable, rate limited, or reports exhausted quota or credits. Any other failure, such as a rejected request or credentials or invalid model output, SHALL be raised without trying another provider, and when the chain is exhausted the last failure SHALL be raised. On a streamed call the router SHALL switch providers only before the first text delta has been delivered; a failure after that SHALL be raised, so one answer never mixes output from two providers. Before calling any provider other than the primary, a streamed call SHALL announce the switch with the provider, model, attempt number, and the reason the previous candidate was left. A served result SHALL report the provider and model that served it, the number of attempts, whether a fallback served it, and its latency measured from the first attempt.

#### Scenario: Primary unavailable
- **WHEN** the primary raises an unavailable failure and the fallback succeeds
- **THEN** the result reports the fallback provider, `fallback_used` true, and 2 attempts

#### Scenario: Exhausted quota falls back
- **WHEN** the primary reports exhausted quota or credits
- **THEN** the fallback serves the request

#### Scenario: Caller or output errors do not fall back
- **WHEN** the primary rejects the request or returns invalid output
- **THEN** that failure is raised and the fallback is never called

#### Scenario: Failure after the first delta
- **WHEN** the primary fails with an unavailable failure after streaming its first text delta
- **THEN** the failure is raised and the fallback is never called

#### Scenario: Latency includes failed attempts
- **WHEN** the primary fails after 60 ms and the fallback serves the request
- **THEN** the result's latency includes the failed attempt, and its `llm_fallback` record carries the failed attempt's own duration

### Requirement: Provider cooldown
The router SHALL count consecutive availability failures per `provider:model`, including failures after the first streamed delta. After `LLM_COOLDOWN_FAILURES` of them it SHALL skip that provider for `LLM_COOLDOWN_SECONDS`; a success SHALL reset the count, and one more failure after the cooldown SHALL start it again. When every provider in the chain is cooling down, the router SHALL still try the primary. Cooldown state SHALL be kept per process.

#### Scenario: Failing primary skipped, then recovered
- **WHEN** the primary has failed `LLM_COOLDOWN_FAILURES` times in a row
- **THEN** the next requests are served by the fallback without calling the primary
- **AND** once the cooldown has elapsed and the primary succeeds, it serves again

#### Scenario: Cooled-down primary on a streamed call
- **WHEN** a streamed request arrives while the primary is cooling down
- **THEN** the router announces the switch to the fallback with cause `cooldown` and attempt 1, without calling the primary

#### Scenario: Every provider cooling down
- **WHEN** every provider in the chain is cooling down
- **THEN** the router still calls the primary

### Requirement: Replay provider
The system SHALL provide a `replay` provider that makes no network calls and needs no API key. It SHALL look up a recorded cassette named by the SHA-256 of the system prompt and the user message (joined by a NUL character) in `REPLAY_CASSETTE_DIR`, and stream the recorded text chunks with the recorded gaps multiplied by `REPLAY_DELAY_SCALE` (0 replays instantly), reporting the recorded usage. When no cassette matches, it SHALL synthesise a stream from one of the reference estimations, chosen deterministically from the prompt pair, with zero usage. It SHALL report provider `replay` and model `replay`, and its final text SHALL be validated against the schema like any provider's.

#### Scenario: Cassette replayed
- **WHEN** a cassette matches the prompt pair
- **THEN** the stream yields the recorded text and ends with a result reporting provider `replay` and the recorded usage

#### Scenario: Recorded pace scaled
- **WHEN** a cassette records chunks at 0, 10, and 35 ms and `REPLAY_DELAY_SCALE` is 2
- **THEN** the provider waits 0, 20, and 50 ms before the chunks

#### Scenario: No cassette
- **WHEN** no cassette matches the prompt pair
- **THEN** the provider streams a reference estimation chosen deterministically from the prompt pair, with zero usage and no cost

#### Scenario: Invalid recording
- **WHEN** a cassette's text is not a schema-valid estimation
- **THEN** the call raises an invalid-output failure
