## Purpose

Loads all runtime settings from the environment (and a local `.env` file) with safe defaults, keeps secrets out of code and logs, and fails fast on invalid configuration.

## ADDED Requirements

### Requirement: Environment settings
The system SHALL load settings from environment variables and an optional `.env` file, with these defaults: `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `APP_ENV=development`, `LOG_LEVEL=DEBUG`; and SHALL read `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` without defaults. Additional tunables (request timeout, max retries, max output tokens, temperature, reasoning effort, maximum transcription length, blended hourly rate, weekly capacity hours per person) SHALL have documented defaults. Temperature and reasoning effort SHALL be applied only when the configured model supports them (see `llm-providers`). The model SHALL be selected by server configuration only, never by API callers.

#### Scenario: Defaults applied
- **WHEN** only `OPENAI_API_KEY` is set
- **THEN** the service starts with provider `openai` and model `gpt-4o-mini`

### Requirement: Fail-fast validation
The system SHALL refuse to start when `LLM_PROVIDER` is not a supported value or when the API key for the selected provider is missing, with an error message naming the missing or invalid variable.

#### Scenario: Missing key for selected provider
- **WHEN** `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` is unset
- **THEN** startup fails with an error naming `ANTHROPIC_API_KEY`

### Requirement: Secret handling
API keys SHALL never appear in source code, logs, error responses, or the string representation of settings. `.env` SHALL be excluded from version control and `.env.example` SHALL list every variable without real values.

#### Scenario: Settings printed
- **WHEN** the settings object is converted to a string or logged
- **THEN** API key values are masked
