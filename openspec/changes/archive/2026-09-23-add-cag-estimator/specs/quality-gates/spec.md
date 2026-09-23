## Purpose

Guarantees on every push and pull request that the project builds, is lint- and type-clean, passes its tests, keeps the structure required by the course brief, leaks no secrets, and has valid specs.

## ADDED Requirements

### Requirement: Continuous integration pipeline
A single CI workflow SHALL run on every push and pull request and SHALL fail if any of these fail: dependency install from the lockfile, lint and format check, static type check, test suite, OpenSpec validation in strict mode, and the check that archived changes have no open tasks. It SHALL require no LLM credentials.

#### Scenario: Lint violation
- **WHEN** a commit introduces a lint violation
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
The test suite SHALL exercise the application end to end — startup, `/health`, `/docs`, and `/api/v1/estimate` success and each error mapping — using a fake provider, with no network access.

#### Scenario: Estimate with fake provider
- **WHEN** the tests post a transcription with the fake provider configured
- **THEN** the endpoint returns `200` with totals matching the fake provider's tasks

### Requirement: Single local check command
The repository SHALL provide one local command that runs the same checks as CI.

#### Scenario: Developer runs check
- **WHEN** a developer runs the local check command
- **THEN** lint, types, tests, and spec validation execute in the same order as CI
