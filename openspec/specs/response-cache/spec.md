# response-cache Specification

## Purpose
Serves repeated identical estimate requests from a shared exact-match cache of validated responses, so a repeat costs no LLM call, while a cache outage or slowdown never fails a request and adds only a bounded delay.

## Requirements

### Requirement: Exact-match response cache
When `REDIS_URL` is set, the system SHALL store each successful estimate response in Redis under a key of the form `estimate:<hex>` (see `Cache key`) for `CACHE_TTL_SECONDS`, and SHALL serve an identical later request from it without calling any provider, on both estimate endpoints. When `REDIS_URL` is unset, the system SHALL use no cache. Failed requests SHALL NOT be cached.

#### Scenario: Repeat served from the cache
- **WHEN** the same transcription is estimated twice
- **THEN** the provider is called once
- **AND** the second response has `metrics.cache_hit` true

#### Scenario: Streamed cache hit
- **WHEN** a transcription that is already cached is sent to the streaming endpoint
- **THEN** the stream contains exactly a `status` event with phase `cache_hit` followed by the `result`

#### Scenario: Failures not cached
- **WHEN** the provider is unavailable for a request
- **THEN** nothing is stored in the cache

#### Scenario: No cache configured
- **WHEN** `REDIS_URL` is unset
- **THEN** every lookup reports the cache status `bypass` and nothing is stored

### Requirement: Cache key
The cache key SHALL be a SHA-256 over canonical JSON of: a cache schema version, the prompt version, a SHA-256 of the rendered system prompt and user message kept as separate values, the provider chain, the generation parameters (temperature, reasoning effort, maximum output tokens), the blended hourly rate and weekly capacity hours (both are computed into the stored totals), and the output schema name. A change to any of them SHALL produce a different key.

#### Scenario: Every input changes the key
- **WHEN** any one of the prompt version, system prompt, user message, chain and parameters, or output schema name changes
- **THEN** the cache key changes

#### Scenario: System prompt and user message kept apart
- **WHEN** two requests split the same text differently between system prompt and user message
- **THEN** their cache keys differ

#### Scenario: Configuration that shapes the stored response
- **WHEN** the model, the fallback chain, the temperature, the reasoning effort, the maximum output tokens, the blended hourly rate, or the weekly capacity hours changes
- **THEN** the cache key changes

### Requirement: Cache-hit response
A response served from the cache SHALL be the stored response with this request's metrics: `cache_hit` true, `cost_usd` 0, `attempts` 0, `fallback_used` false, no `ttft_ms`, and `latency_ms` equal to the lookup's duration. A cache hit SHALL log one `estimate_cache_hit` record with provider, model, prompt version, latency, and whether it streamed, and SHALL log no `llm_call` record.

#### Scenario: Hit metrics and logs
- **WHEN** a request is served from the cache
- **THEN** its body equals the stored response except for `metrics`
- **AND** `metrics.cost_usd` is 0, `metrics.attempts` is 0, and `metrics.ttft_ms` is null
- **AND** one `estimate_cache_hit` record is logged and no `llm_call` record

### Requirement: Regenerate bypasses the cache
A request with `refresh=true` SHALL skip the cache lookup, call the provider, log its `llm_call` with cache status `bypass`, and replace the stored entry with the fresh response, so later identical requests get the regenerated answer.

#### Scenario: Refresh regenerates and overwrites
- **WHEN** a cached transcription is sent again with `refresh=true`, to either estimate endpoint
- **THEN** the provider is called and the response has `metrics.cache_hit` false
- **AND** the next identical request without `refresh` is served from the cache with the regenerated answer

### Requirement: Fail-open cache
A Redis failure SHALL never fail a request. Each cache read and each write SHALL be bounded to 0.2 s of wall-clock time, connection setup included, so the cache adds at most about 0.4 s to a request. A failed or timed-out read SHALL count as a miss with cache status `error`, and the system SHALL then skip the write for that request; a failed write SHALL be ignored. Each failure SHALL log a `cache_error` warning with the operation and the exception class only, never the key or the exception message. A stored entry that no longer validates as a response SHALL count as a miss.

#### Scenario: Redis down
- **WHEN** Redis refuses connections during a blocking or streamed request
- **THEN** the request is served by the provider and its `llm_call` record has cache status `error`

#### Scenario: Redis slow but alive
- **WHEN** Redis answers every command, but each reply takes 0.1 s
- **THEN** the request completes within 0.5 s and its `llm_call` record has cache status `error`
- **AND** a streamed request sends its first event within 0.25 s

#### Scenario: Redis hung
- **WHEN** Redis accepts connections and never answers
- **THEN** the request completes within 0.5 s

#### Scenario: Error logged without the key
- **WHEN** a cache read and a write fail
- **THEN** two `cache_error` warnings name the operations `get` and `set` and the exception class
- **AND** no log record contains the cache key

#### Scenario: Stale entry
- **WHEN** a stored entry is not a valid response
- **THEN** the lookup counts as a miss

### Requirement: Streamed responses cached on delivery
A streamed response SHALL be stored only after the client has received its `result` event. A stream that the client leaves earlier, including after the provider has finished but before the `result` was delivered, SHALL store nothing.

#### Scenario: Completed stream cached
- **WHEN** a client reads a stream through its `result`
- **THEN** the next identical request is served from the cache

#### Scenario: Client leaves before the result
- **WHEN** the client leaves a stream after the first `partial`, or after the `validating` status
- **THEN** nothing is stored in the cache
