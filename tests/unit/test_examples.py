import pytest

from app.context.examples import REFERENCE_ESTIMATIONS, ReferenceEstimation
from app.schemas.estimation import EstimationBreakdown
from app.services.estimation_math import compute_totals
from app.services.grounding import check_grounding

NON_BUILD_PHASES = {"qa", "devops", "project_management"}


def test_at_least_two_references_of_different_sizes() -> None:
    assert len(REFERENCE_ESTIMATIONS) >= 2
    assert {r.size for r in REFERENCE_ESTIMATIONS} == {"small", "medium", "large"}


@pytest.mark.parametrize("ref", REFERENCE_ESTIMATIONS, ids=lambda r: r.size)
def test_reference_validates_against_contract(ref: ReferenceEstimation) -> None:
    EstimationBreakdown.model_validate(ref.estimation.model_dump())


@pytest.mark.parametrize("ref", REFERENCE_ESTIMATIONS, ids=lambda r: r.size)
def test_reference_fully_grounded(ref: ReferenceEstimation) -> None:
    report = check_grounding(ref.estimation, ref.meeting_summary)
    assert report.score == 1.0, report.ungrounded_requirement_ids
    assert report.tasks_without_valid_basis == []


@pytest.mark.parametrize("ref", REFERENCE_ESTIMATIONS, ids=lambda r: r.size)
def test_reference_follows_prompt_rules(ref: ReferenceEstimation) -> None:
    assert {t.phase for t in ref.estimation.tasks} >= NON_BUILD_PHASES
    assert all(4 <= t.likely_hours <= 80 for t in ref.estimation.tasks)
    assert ref.estimation.open_questions


def test_sizes_are_ordered() -> None:
    totals = {
        r.size: compute_totals(
            r.estimation, weekly_capacity_hours=30, hourly_rate=None
        ).expected_hours
        for r in REFERENCE_ESTIMATIONS
    }
    assert totals["small"] < totals["medium"] < totals["large"]
