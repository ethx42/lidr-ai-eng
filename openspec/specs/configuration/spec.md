# configuration Specification

## Purpose
Loads all runtime settings from the environment (and a local `.env` file) with safe defaults, keeps secrets out of code and logs, and fails fast on invalid configuration.

## Requirements

### Requirement: Environment settings
The system SHALL load settings from environment variables and an optional `.env` file, with these defaults: `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `APP_ENV=development`, `LOG_LEVEL=DEBUG`; and SHALL read `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` without defaults. Additional tunables (request timeout, max retries, max output tokens, temperature, reasoning effort, maximum transcription length, blended hourly rate, weekly capacity hours per person) SHALL have documented defaults. An empty value SHALL count as unset.

The system SHALL also read these settings, with these defaults:
- `LLM_FALLBACKS=anthropic:claude-haiku-4-5`: comma-separated `provider:model` entries tried in order after the primary; `none` (in any case) disables fallback, and an empty value keeps the default
- `LLM_COOLDOWN_FAILURES=3` (at least 1) and `LLM_COOLDOWN_SECONDS=30` (not negative): see `llm-providers`
- `REDIS_URL` (unset: no response cache) and `CACHE_TTL_SECONDS=86400`: see `response-cache`
- `REPLAY_CASSETTE_DIR=tests/cassettes` and `REPLAY_DELAY_SCALE=1` (not negative): see the replay provider in `llm-providers`
- `ALLOWED_HOSTS=localhost,127.0.0.1,ai-service,testserver`: comma-separated host names, without a port, that the API answers (see the host allowlist in `estimation-api`); an empty value keeps the default
- `PROMPT_VERSION=v2`: the prompt version used when a single-shot request names none (see `Prompt version selection` in `estimation-api` and `Prompt versioning` in `prompt-context`); session turns always use `v3`, and no setting changes that (see `Session prompt version` in `conversation-sessions`)
- `MAX_TURNS=6`, `MAX_HISTORY_CHARS=60000`, `SESSION_TTL_SECONDS=7200`, and `MAX_SESSIONS=1000`, each at least 1: the history window and the session store (see `conversation-sessions`)
- `ATTACHMENT_MAX_FILES=5`, `ATTACHMENT_MAX_BYTES=10485760` (10 MiB), `ATTACHMENT_MAX_PAGES=200`, `ATTACHMENT_MAX_CHARS=50000`, and `ATTACHMENT_MAX_DOCX_UNCOMPRESSED=52428800` (50 MiB), each at least 1: the per-turn attachment budgets (see `Attachments` in `conversation-sessions`); the request body limit follows from the first two (see `Request body limit` in `estimation-api`)
- `ATTACHMENT_TIMEOUT_SECONDS=10` (above 0, at most 120), `ATTACHMENT_MAX_MEMORY_BYTES=536870912` (512 MiB; from 128 MiB to 8 GiB), and `ATTACHMENT_MAX_CONCURRENT=2` (from 1 to 16): the extraction child processes (see `Attachment isolation` in `conversation-sessions`)

The provider chain SHALL be the primary (`LLM_PROVIDER` with `LLM_MODEL`, or model `replay` for the replay provider) followed by the `LLM_FALLBACKS` entries. Reasoning effort SHALL accept `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`, and startup SHALL fail with an error naming `LLM_REASONING_EFFORT` for any other value. Temperature and reasoning effort SHALL be applied only when the configured model supports them (see `llm-providers`). The model SHALL be selected by server configuration only, never by API callers.

#### Scenario: Defaults applied
- **WHEN** only `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are set
- **THEN** the chain is `openai:gpt-4o-mini` followed by `anthropic:claude-haiku-4-5`, with a cooldown of 3 failures and 30 seconds

#### Scenario: Single provider
- **WHEN** only `OPENAI_API_KEY` is set and `LLM_FALLBACKS=none`
- **THEN** the service starts with provider `openai`, model `gpt-4o-mini`, and no fallback

#### Scenario: Fallback chain parsed
- **WHEN** `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-5`, and `LLM_FALLBACKS=" openai:gpt-4.1-mini , anthropic:claude-haiku-4-5,replay:replay"`
- **THEN** the chain is `anthropic:claude-sonnet-4-5`, `openai:gpt-4.1-mini`, `anthropic:claude-haiku-4-5`, `replay:replay`

#### Scenario: Empty fallback value keeps the default
- **WHEN** `LLM_FALLBACKS` is set to an empty value
- **THEN** the chain still ends with `anthropic:claude-haiku-4-5`

#### Scenario: Default prompt version
- **WHEN** `PROMPT_VERSION` is unset
- **THEN** single-shot requests without a `prompt_version` parameter are rendered from `v2`, and session turns from `v3`

#### Scenario: Session and attachment defaults
- **WHEN** none of the session or attachment settings is set
- **THEN** the history keeps 6 turns and 60,000 characters, sessions expire after 7,200 idle seconds with at most 1,000 held, and a turn takes up to 5 attachments of 10 MiB each, read by at most 2 child processes at once with a 10-second timeout

#### Scenario: Attachment setting out of range
- **WHEN** `ATTACHMENT_TIMEOUT_SECONDS=0` or `ATTACHMENT_MAX_CONCURRENT=17`
- **THEN** startup fails with an error naming that variable

#### Scenario: Extended effort level accepted
- **WHEN** `LLM_REASONING_EFFORT=xhigh`
- **THEN** the settings load with reasoning effort `xhigh`

#### Scenario: Invalid effort level
- **WHEN** `LLM_REASONING_EFFORT=extreme`
- **THEN** startup fails with an error naming `LLM_REASONING_EFFORT`

### Requirement: Fail-fast validation
The system SHALL refuse to start when `LLM_PROVIDER` is not a supported value, when an `LLM_FALLBACKS` entry is not `provider:model` with a supported provider and a model, when a numeric setting is out of range, when `ALLOWED_HOSTS` lists no host name or an entry with a port, when `PROMPT_VERSION` names no available prompt version, when any available prompt version fails to render with the default choices (`web_saas`, `medium`, `phases_table`), or when the API key of any provider in the chain (primary or fallback) is missing or blank, with an error message naming the missing or invalid variable. The `replay` provider SHALL need no key. For a missing fallback key, the error SHALL also say that `LLM_FALLBACKS=none` disables the fallback.

#### Scenario: Missing key for selected provider
- **WHEN** `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` is unset
- **THEN** startup fails with an error naming `ANTHROPIC_API_KEY`

#### Scenario: Missing key for a fallback
- **WHEN** only `OPENAI_API_KEY` is set and `LLM_FALLBACKS` keeps its default
- **THEN** startup fails with an error naming `ANTHROPIC_API_KEY` and `LLM_FALLBACKS=none`

#### Scenario: Malformed fallback entry
- **WHEN** `LLM_FALLBACKS` is `acme:model-1`, `anthropic`, `anthropic:`, `:gpt-4o-mini`, or `,`
- **THEN** startup fails with an error naming `LLM_FALLBACKS`

#### Scenario: Allowed host with a port
- **WHEN** `ALLOWED_HOSTS=localhost:8000`
- **THEN** startup fails with an error naming `ALLOWED_HOSTS`

#### Scenario: Unknown prompt version
- **WHEN** `PROMPT_VERSION=v999`
- **THEN** startup fails with an error naming `PROMPT_VERSION` and the available versions

#### Scenario: Broken template
- **WHEN** a prompt version's user template uses a variable the loader does not pass
- **THEN** startup fails with an undefined-variable error, before any request is served

#### Scenario: Replay needs no key
- **WHEN** `LLM_PROVIDER=replay`, `LLM_FALLBACKS=none`, and no API key is set
- **THEN** the service starts with the chain `replay:replay`

### Requirement: Secret handling
API keys and `REDIS_URL` (which can carry a password) SHALL never appear in source code, logs, error responses, startup validation errors, or the string representation of settings. `.env` SHALL be excluded from version control and `.env.example` SHALL list every variable without real values.

#### Scenario: Settings printed
- **WHEN** the settings object is converted to a string or logged
- **THEN** API key values are masked

#### Scenario: Startup error with a key present
- **WHEN** startup fails because the fallback's key is missing while `OPENAI_API_KEY` is set
- **THEN** the validation error does not contain the `OPENAI_API_KEY` value

#### Scenario: Redis password masked
- **WHEN** `REDIS_URL` contains a password and the settings are printed
- **THEN** the password does not appear
