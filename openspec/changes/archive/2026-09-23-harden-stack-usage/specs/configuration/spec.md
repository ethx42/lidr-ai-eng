## MODIFIED Requirements

### Requirement: Environment settings
The system SHALL load settings from environment variables and an optional `.env` file, with these defaults: `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `APP_ENV=development`, `LOG_LEVEL=DEBUG`; and SHALL read `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` without defaults. Additional tunables (request timeout, max retries, max output tokens, temperature, reasoning effort, maximum transcription length, blended hourly rate, weekly capacity hours per person) SHALL have documented defaults. Reasoning effort SHALL accept `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`, and startup SHALL fail with an error naming `LLM_REASONING_EFFORT` for any other value. Temperature and reasoning effort SHALL be applied only when the configured model supports them (see `llm-providers`). The model SHALL be selected by server configuration only, never by API callers.

#### Scenario: Defaults applied
- **WHEN** only `OPENAI_API_KEY` is set
- **THEN** the service starts with provider `openai` and model `gpt-4o-mini`

#### Scenario: Extended effort level accepted
- **WHEN** `LLM_REASONING_EFFORT=xhigh`
- **THEN** the settings load with reasoning effort `xhigh`

#### Scenario: Invalid effort level
- **WHEN** `LLM_REASONING_EFFORT=extreme`
- **THEN** startup fails with an error naming `LLM_REASONING_EFFORT`
