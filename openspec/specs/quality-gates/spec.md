# quality-gates Specification

## Purpose
Guarantees on every push and pull request that the AI service and the web client build, are lint- and type-clean, pass their tests, keep the structure required by the course brief and the committed API contract, leak no secrets, and have valid specs; and gives each branch an offline browser end-to-end check.

## Requirements

### Requirement: Continuous integration pipeline
A single CI workflow SHALL run on every push and pull request and SHALL fail if any of these fail: dependency install from the Python and web lockfiles, lint and format check, static type check, test suite, OpenSpec validation in strict mode, the check that archived changes have no open tasks, the web client checks, validation of the Compose files without printing their resolved values, and the build of every container image. It SHALL require no LLM credentials.

#### Scenario: Lint violation
- **WHEN** a commit introduces a lint violation
- **THEN** the CI run fails

#### Scenario: Image no longer builds
- **WHEN** a commit breaks the build of the AI service or web image
- **THEN** the CI run fails

### Requirement: Required project structure
The test suite SHALL verify that every path required by the course brief exists: `app/__init__.py`, `app/main.py`, `app/config.py`, `app/routers/__init__.py`, `app/routers/estimations.py`, `app/services/__init__.py`, `app/services/llm_service.py`, `app/context/__init__.py`, `app/context/examples.py`, `.env.example`, `.gitignore`, `pyproject.toml`, `README.md`.

#### Scenario: Required file removed
- **WHEN** `app/context/examples.py` is deleted
- **THEN** the structure test fails

### Requirement: Secret hygiene checks
The test suite SHALL verify that `.env` is ignored by git and that no tracked file contains a string shaped like an OpenAI or Anthropic API key.

#### Scenario: Key committed
- **WHEN** a tracked file contains a string matching an API key pattern
- **THEN** the secret hygiene test fails

### Requirement: Offline end-to-end test
The test suite SHALL exercise the application end to end — startup, `/health`, `/docs`, `/api/v1/context`, and both estimate endpoints with success and each error mapping — using fake providers, an in-memory Redis, and SDK clients on mock transports that serve recorded provider streams, with no network access beyond the local machine.

#### Scenario: Estimate with fake provider
- **WHEN** the tests post a transcription with the fake provider configured
- **THEN** the endpoint returns `200` with totals matching the fake provider's tasks

#### Scenario: Streamed estimate with fake provider
- **WHEN** the tests post a transcription to the streaming endpoint with the fake provider configured
- **THEN** the stream ends with exactly one `result` event

### Requirement: Single local check command
The repository SHALL provide one local command that runs the same code checks as CI: lint, types, tests, spec validation, and the web client checks. The Compose validation and image builds run in CI only.

#### Scenario: Developer runs check
- **WHEN** a developer runs the local check command
- **THEN** lint, types, tests, spec validation, and the web client checks execute in the same order as CI

### Requirement: Runtime dependencies declared
Every third-party package imported by application code SHALL be declared as a direct runtime dependency, not only installed transitively or by the development dependency group, so its supported versions are stated and a production install without development dependencies can start the application. The test suite SHALL verify this.

#### Scenario: Import provided only by a dev dependency
- **WHEN** application code imports a package that only the development dependency group declares
- **THEN** the dependency test fails naming that package

#### Scenario: Import provided only transitively
- **WHEN** application code imports a package that is installed only as a dependency of another runtime dependency
- **THEN** the dependency test fails naming that package

### Requirement: Reproducible toolchain
The project SHALL pin the range of package-manager versions it supports in its project configuration, so local runs and CI use a compatible package manager. CI SHALL refuse to update the lockfile implicitly during any step, not only during install. The test suite SHALL verify that both settings are present.

#### Scenario: Lockfile out of date in CI
- **WHEN** `pyproject.toml` changes without a matching `uv.lock` update
- **THEN** the CI run fails instead of re-locking

#### Scenario: Pin removed
- **WHEN** the package-manager version pin is removed from the project configuration
- **THEN** the toolchain test fails

### Requirement: Web client checks
The web client checks SHALL run lint with no warnings allowed, type checking with the framework's generated route types, the unit test suite, and a check that the TypeScript types generated from the committed API contract are current.

#### Scenario: Web lint warning
- **WHEN** a web source file introduces a lint warning
- **THEN** the local check command fails

#### Scenario: Stale web types
- **WHEN** the committed API contract changes without regenerating the web client's types
- **THEN** the local check command fails

### Requirement: Committed API contract
The AI service's OpenAPI contract SHALL be committed, including the schemas of every stream event payload and of every response model, with fields that are always serialized marked required. The test suite SHALL fail when the committed contract differs from the one the application generates.

#### Scenario: Stale contract
- **WHEN** an API model changes without regenerating the committed contract
- **THEN** the contract snapshot test fails

#### Scenario: Stream events documented
- **WHEN** the contract is generated
- **THEN** the streaming operation's `200` response lists the `StatusEvent`, `PartialEvent`, `EstimateResponse`, and `ErrorEvent` schemas

### Requirement: Browser end-to-end tests
The repository SHALL provide a command that runs browser end-to-end tests against the whole system started with Docker Compose in its offline configuration: the replay provider, no fallback, no response cache, and no API keys, so it makes no LLM calls. The tests SHALL cover streaming a sample estimate from the typed form to completion, a requirement highlighting its quote in the transcript on hover and on keyboard focus, the Document view following the output format, Stop and Regenerate, keyboard-only use, a 375 px viewport (transcript and estimate as tabs) without horizontal scrolling, and short viewports keeping the estimate usable, and SHALL fail on any serious or critical accessibility violation, in the light and dark themes. The branch close gate SHALL run them.

#### Scenario: Estimate streamed in the browser
- **WHEN** the tests send a sample transcript with the form's choices
- **THEN** a partial estimate renders before the totals, and the completed estimate shows its totals, its tasks grouped by phase, and the call in the inspector

#### Scenario: Accessibility violation
- **WHEN** a page state the tests visit has a serious or critical accessibility violation
- **THEN** the end-to-end run fails

### Requirement: Compose posture checks
The test suite SHALL verify the Compose files: every published port binds to the loopback interface; in the base file only the web service publishes a port; Redis is never published; only the AI service reads env files; no value interpolates the host shell; and the end-to-end override drops the env files and runs the replay provider without fallback or cache.

#### Scenario: Port published on every interface
- **WHEN** a Compose file publishes a port without binding it to `127.0.0.1`
- **THEN** the posture test fails

#### Scenario: Host shell interpolation
- **WHEN** a Compose value uses `${...}`
- **THEN** the posture test fails
