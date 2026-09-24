## Purpose

Measures prompt quality against a golden set of transcriptions using the real configured provider, so prompt iterations can be compared by version rather than by impression.

## ADDED Requirements

### Requirement: Golden set
The repository SHALL contain a golden set of at least three meeting transcriptions, including the course exercise transcription, one deliberately vague transcription, and one case that requests an explicit output language different from the transcription's language. A golden case MAY declare the `output_language` it is evaluated with.

#### Scenario: Golden set present
- **WHEN** the evaluation is started
- **THEN** it runs over every transcription in the golden set

### Requirement: Explicitly invoked live evaluation
The evaluation SHALL use the configured provider and model and SHALL run only when explicitly invoked, by a developer or by a dedicated evaluation gate. It SHALL never be part of the default quality gate (the local check command or the default CI workflow).

#### Scenario: Default quality gate
- **WHEN** the default quality gate runs locally or in CI
- **THEN** no live evaluation is executed and no provider credentials are required

#### Scenario: Explicit invocation
- **WHEN** a developer or an evaluation gate invokes the evaluation with provider credentials available
- **THEN** it runs over the golden set with the configured provider and model

### Requirement: Automated checks
For each golden transcription the evaluation SHALL record: schema validity, three-point ordering, task hours within bounds, coverage of non-build phases (QA, deployment, project management), presence of open questions for the vague transcription, whether the narrative is written in the expected language (the case's `output_language` when declared, otherwise the transcription's language), grounding score, ungrounded requirements, tasks without a valid basis, latency, and token usage (including cached tokens). A case SHALL pass grounding only when every requirement is grounded and every task has a valid basis.

#### Scenario: Fabricated requirement in eval
- **WHEN** a golden case produces a requirement whose evidence is not in the transcription
- **THEN** the case is reported as failing grounding with that requirement's identifier

#### Scenario: Narrative in the wrong language
- **WHEN** a case's narrative fields are written in a language other than the expected one
- **THEN** the case's language check fails

#### Scenario: Vague transcription
- **WHEN** the vague transcription is evaluated
- **THEN** the report records whether at least one open question and a confidence below `high` were produced

### Requirement: Versioned report with an aggregate score
Each evaluation run SHALL write a JSON report containing the prompt version, provider, model, timestamp, per-case results, the case pass rate, and a top-level `score` between 0 and 1 defined as the fraction of individual checks passed across all cases. By default the report SHALL be written to a file named with the prompt version and a timestamp; when an explicit output path is given, the report SHALL be written to exactly that path.

#### Scenario: Default report location
- **WHEN** an evaluation completes without an explicit output path
- **THEN** a report file exists whose name includes the active prompt version

#### Scenario: Explicit report path
- **WHEN** the evaluation is invoked with an explicit output path
- **THEN** the report is written to that path and its top-level `score` is a number between 0 and 1

#### Scenario: Score granularity
- **WHEN** three cases run and one check fails in one case while every other check passes
- **THEN** `score` is below 1 and above the case pass rate of that run

### Requirement: Versioned baseline
The repository SHALL keep a committed baseline report of the evaluation, produced by an explicit command from a completed run, so that later prompt or model changes can be compared against it.

#### Scenario: Baseline recorded
- **WHEN** the developer records a baseline from a completed evaluation run
- **THEN** the baseline file contains that run's `score`, prompt version, provider, and model
