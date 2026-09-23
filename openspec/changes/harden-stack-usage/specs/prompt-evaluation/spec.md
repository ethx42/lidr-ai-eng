## MODIFIED Requirements

### Requirement: Automated checks
For each golden transcription the evaluation SHALL record: schema validity, three-point ordering, task hours within bounds, coverage of non-build phases (QA, deployment, project management), presence of open questions for the vague transcription, whether the narrative is written in the expected language (the case's `output_language` when declared, otherwise the transcription's language), grounding score, ungrounded requirements, tasks without a valid basis, latency, and token usage (including cached input and cache write tokens). A case SHALL pass grounding only when every requirement is grounded and every task has a valid basis.

#### Scenario: Fabricated requirement in eval
- **WHEN** a golden case produces a requirement whose evidence is not in the transcription
- **THEN** the case is reported as failing grounding with that requirement's identifier

#### Scenario: Narrative in the wrong language
- **WHEN** a case's narrative fields are written in a language other than the expected one
- **THEN** the case's language check fails

#### Scenario: Vague transcription
- **WHEN** the vague transcription is evaluated
- **THEN** the report records whether at least one open question and a confidence below `high` were produced

#### Scenario: Cache usage recorded
- **WHEN** a case completes
- **THEN** its usage in the report contains `cached_input_tokens` and `cache_write_tokens`
