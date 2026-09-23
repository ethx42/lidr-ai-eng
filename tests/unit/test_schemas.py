import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.estimation import EstimateRequest, EstimationBreakdown
from tests.factories import breakdown, breakdown_data, task

UNSUPPORTED_KEYWORDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
    "uniqueItems",
    "default",
    "const",
}


def walk(node: Any) -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        return [(k, v) for k, v in node.items()] + [p for v in node.values() for p in walk(v)]
    if isinstance(node, list):
        return [p for v in node for p in walk(v)]
    return []


def refs(node: Any) -> set[str]:
    return {v.rsplit("/", 1)[-1] for k, v in walk(node) if k == "$ref"}


def test_valid_breakdown() -> None:
    assert len(breakdown().tasks) == 2


@pytest.mark.parametrize(
    "hours",
    [(12, 10, 18), (8, 20, 18), (0, 1, 2), (1, 2, 1000)],
    ids=["o>m", "m>p", "zero", "too-large"],
)
def test_rejects_invalid_three_point(hours: tuple[float, float, float]) -> None:
    with pytest.raises(ValidationError):
        breakdown(tasks=[task(hours=hours)])


def test_rejects_empty_basis() -> None:
    with pytest.raises(ValidationError, match="basis"):
        breakdown(tasks=[task(basis=[])])


@pytest.mark.parametrize(
    "field,items",
    [
        ("requirements", [{"id": "X1", "statement": "s", "evidence": "e"}]),
        ("assumptions", [{"id": "R1", "statement": "s", "impact_if_wrong": "i"}]),
        ("tasks", [task("T1"), task("T1")]),
    ],
    ids=["bad-requirement-id", "bad-assumption-id", "duplicate-task-id"],
)
def test_rejects_bad_identifiers(field: str, items: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        breakdown(**{field: items})


def test_rejects_no_tasks() -> None:
    with pytest.raises(ValidationError):
        breakdown(tasks=[])


def test_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        breakdown(requirements=[{"id": "R1", "statement": "s", "evidence": "  "}])


def test_json_schema_is_provider_safe() -> None:
    schema = EstimationBreakdown.model_json_schema()
    used = {k for k, _ in walk(schema)}
    assert not used & UNSUPPORTED_KEYWORDS
    for name, definition in schema.get("$defs", {}).items():
        assert name not in refs(definition), f"recursive definition: {name}"
    assert all(set(d["required"]) == set(d["properties"]) for d in schema["$defs"].values())
    assert set(schema["required"]) == set(schema["properties"])


def test_json_schema_describes_every_field() -> None:
    schema = EstimationBreakdown.model_json_schema()
    models = [schema, *schema["$defs"].values()]
    missing = [
        f"{m['title']}.{name}"
        for m in models
        for name, prop in m["properties"].items()
        if "description" not in prop
    ]
    assert not missing


def test_understanding_fields_precede_tasks() -> None:
    fields = list(EstimationBreakdown.model_fields)
    assert fields.index("requirements") < fields.index("tasks")
    assert fields.index("open_questions") < fields.index("tasks")


def test_request_strips_and_rejects_blank() -> None:
    assert EstimateRequest(transcription="  hi  ").transcription == "hi"
    with pytest.raises(ValidationError):
        EstimateRequest(transcription="   ")


def test_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EstimateRequest.model_validate({"transcription": "hi", "model": "gpt-5"})


def test_breakdown_data_round_trips() -> None:
    data = breakdown_data()
    assert breakdown().model_dump() == EstimationBreakdown.model_validate(data).model_dump()


# The LLM-facing contract: a refactor of validators must not change what providers receive.
SCHEMA_SHA256 = "1e5dd56a894d1e91ade0e7882cdf5fb5720900414365bedf40ebcfaacabd94fc"


def test_json_schema_unchanged() -> None:
    schema = json.dumps(EstimationBreakdown.model_json_schema(), sort_keys=True)
    assert hashlib.sha256(schema.encode()).hexdigest() == SCHEMA_SHA256


def error_locs(overrides: dict[str, Any]) -> list[tuple[int | str, ...]]:
    with pytest.raises(ValidationError) as info:
        breakdown(**overrides)
    return [tuple(e["loc"]) for e in info.value.errors()]


@pytest.mark.parametrize(
    "overrides,loc",
    [
        (
            {"requirements": [{"id": "R1", "statement": "s", "evidence": " "}]},
            ("requirements", 0, "evidence"),
        ),
        ({"tasks": [task(basis=[])]}, ("tasks", 0, "basis")),
        ({"team": [{"role": "Dev", "count": 0}]}, ("team", 0, "count")),
        ({"requirements": [{"id": "X1", "statement": "s", "evidence": "e"}]}, ("requirements",)),
        ({"tasks": []}, ("tasks",)),
    ],
    ids=["blank-evidence", "empty-basis", "zero-count", "bad-id", "no-tasks"],
)
def test_single_field_rules_report_the_field(
    overrides: dict[str, Any], loc: tuple[int | str, ...]
) -> None:
    assert error_locs(overrides) == [loc]
