"""Estimation contract.

`EstimationBreakdown` is the schema the LLM must return. Its constraints live in validators,
not in JSON-schema keywords, so the schema stays within what both providers' structured
outputs support. Field order matters: understanding fields precede numbers.
"""

import re
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Phase = Literal[
    "discovery",
    "ux_ui",
    "backend",
    "frontend",
    "integrations",
    "qa",
    "devops",
    "project_management",
]
Level = Literal["low", "medium", "high"]

MIN_TASK_HOURS = 0.5
MAX_TASK_HOURS = 400


def _check_ids(prefix: str, ids: list[str]) -> None:
    bad = [i for i in ids if not re.fullmatch(rf"{prefix}[1-9]\d*", i)]
    if bad:
        raise ValueError(f"identifiers must look like {prefix}1, {prefix}2, ...: {bad}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate {prefix} identifiers: {ids}")


class Requirement(BaseModel):
    id: str = Field(description="Identifier R1, R2, ... in order of appearance.")
    statement: str = Field(description="What the client needs, in the output language.")
    evidence: str = Field(
        description=(
            "Exact verbatim quote from the transcript that states this requirement, "
            "copied character for character in the transcript's original language."
        )
    )

    @model_validator(mode="after")
    def evidence_not_blank(self) -> Self:
        if not self.evidence.strip():
            raise ValueError(f"{self.id}: evidence must not be empty")
        return self


class Assumption(BaseModel):
    id: str = Field(description="Identifier A1, A2, ...")
    statement: str = Field(description="Something not stated in the transcript that we assume.")
    impact_if_wrong: str = Field(description="How the estimate changes if the assumption fails.")


class Task(BaseModel):
    id: str = Field(description="Identifier T1, T2, ...")
    phase: Phase = Field(description="Delivery phase this task belongs to.")
    name: str = Field(description="Short task name.")
    rationale: str = Field(description="Why this task is needed and what drives its size.")
    basis: list[str] = Field(
        description="Requirement and/or assumption identifiers (R*, A*) this task rests on."
    )
    optimistic_hours: float = Field(description="Best-case effort in hours.")
    likely_hours: float = Field(description="Most likely effort in hours.")
    pessimistic_hours: float = Field(description="Worst-case effort in hours.")

    @model_validator(mode="after")
    def check_task(self) -> Self:
        if not self.basis:
            raise ValueError(f"{self.id}: basis must cite at least one requirement or assumption")
        o, m, p = self.optimistic_hours, self.likely_hours, self.pessimistic_hours
        if not o <= m <= p:
            raise ValueError(f"{self.id}: hours must satisfy optimistic <= likely <= pessimistic")
        if o < MIN_TASK_HOURS or p > MAX_TASK_HOURS:
            raise ValueError(f"{self.id}: hours must be within {MIN_TASK_HOURS}-{MAX_TASK_HOURS}")
        return self


class TeamMember(BaseModel):
    role: str = Field(description="Role name, e.g. Backend developer.")
    count: int = Field(description="Number of people in this role.")

    @model_validator(mode="after")
    def positive_count(self) -> Self:
        if self.count < 1:
            raise ValueError(f"{self.role}: count must be at least 1")
        return self


class Risk(BaseModel):
    description: str = Field(description="What could go wrong.")
    impact: Level = Field(description="Impact on schedule or cost.")
    mitigation: str = Field(description="How to reduce or handle the risk.")


class EstimationBreakdown(BaseModel):
    project_name: str = Field(description="Short project name.")
    summary: str = Field(description="Two to four sentences describing the project scope.")
    requirements: list[Requirement] = Field(
        description="Requirements explicitly stated in the transcript, each with verbatim evidence."
    )
    assumptions: list[Assumption] = Field(
        description="Gaps filled with explicit assumptions instead of invented scope."
    )
    open_questions: list[str] = Field(description="Questions to ask the client before committing.")
    tasks: Sequence[Task] = Field(
        description=(
            "Work breakdown across phases, including QA, deployment (devops) and project "
            "management. Do not compute totals."
        )
    )
    team: list[TeamMember] = Field(description="Recommended team composition.")
    risks: list[Risk] = Field(description="Main delivery risks.")
    confidence: Level = Field(description="Confidence in this estimate; low for vague input.")
    confidence_rationale: str = Field(description="Why this confidence level.")

    @model_validator(mode="after")
    def check_identifiers(self) -> Self:
        if not self.tasks:
            raise ValueError("at least one task is required")
        _check_ids("R", [r.id for r in self.requirements])
        _check_ids("A", [a.id for a in self.assumptions])
        _check_ids("T", [t.id for t in self.tasks])
        return self


class EstimatedTask(Task):
    expected_hours: float = Field(description="PERT expected hours, computed in code.")


class Totals(BaseModel):
    expected_hours: float
    optimistic_hours: float
    pessimistic_hours: float
    team_size: int
    weekly_capacity_hours: float
    duration_weeks_min: float
    duration_weeks_max: float
    hourly_rate: float | None
    estimated_cost: float | None


class EnrichedBreakdown(EstimationBreakdown):
    tasks: Sequence[EstimatedTask]
    totals: Totals


class GroundingReport(BaseModel):
    requirements_total: int
    requirements_grounded: int
    ungrounded_requirement_ids: list[str]
    tasks_without_valid_basis: list[str]
    score: float


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class EstimateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "transcription": (
                        "Client: We run three yoga studios and want customers to book and pay "
                        "for classes online from their phones..."
                    ),
                    "output_language": "English",
                }
            ]
        },
    )

    transcription: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="Meeting transcription to estimate. Treated strictly as data."
    )
    output_language: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None
    ) = Field(
        default=None,
        description="Language for narrative fields. Defaults to the transcription's language.",
    )


class EstimateResponse(BaseModel):
    estimation: str = Field(description="Estimation rendered as markdown.")
    breakdown: EnrichedBreakdown
    grounding: GroundingReport
    model: str
    provider: Literal["openai", "anthropic"]
    prompt_version: str
    usage: Usage
