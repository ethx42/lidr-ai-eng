## Purpose

Measures prompt quality against a golden set of transcriptions using the real configured provider, so prompt iterations can be compared by version rather than by impression.

## ADDED Requirements

### Requirement: Golden set
The repository SHALL contain a golden set of at least three meeting transcriptions, including the course exercise transcription and one deliberately vague transcription.

#### Scenario: Golden set present
- **WHEN** the evaluation is started
- **THEN** it runs over every transcription in the golden set

### Requirement: Opt-in live evaluation
The evaluation SHALL run only when explicitly invoked by a developer, SHALL use the configured provider and model, and SHALL NOT run as part of automated CI.

#### Scenario: CI run
- **WHEN** the CI pipeline runs
- **THEN** no live evaluation is executed and no provider credentials are required

### Requirement: Automated checks
For each golden transcription the evaluation SHALL record: schema validity, three-point ordering, task hours within bounds, coverage of non-build phases (QA, deployment, project management), presence of open questions for the vague transcription, grounding score, ungrounded requirements, tasks without a valid basis, latency, and token usage (including cached tokens). A case SHALL pass grounding only when every requirement is grounded and every task has a valid basis.

#### Scenario: Fabricated requirement in eval
- **WHEN** a golden case produces a requirement whose evidence is not in the transcription
- **THEN** the case is reported as failing grounding with that requirement's identifier

#### Scenario: Vague transcription
- **WHEN** the vague transcription is evaluated
- **THEN** the report records whether at least one open question and a confidence below `high` were produced

### Requirement: Versioned report
Each evaluation run SHALL write a JSON report named with the prompt version and a timestamp, containing per-case results, an aggregate pass rate, provider, and model.

#### Scenario: Report written
- **WHEN** an evaluation completes
- **THEN** a report file exists whose name includes the active prompt version
