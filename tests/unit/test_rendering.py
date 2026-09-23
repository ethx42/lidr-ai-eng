import re

from app.schemas.estimation import GroundingReport
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.rendering import render_markdown
from tests.factories import TRANSCRIPT, breakdown, task

GROUNDED = GroundingReport(
    requirements_total=2,
    requirements_grounded=2,
    ungrounded_requirement_ids=[],
    tasks_without_valid_basis=[],
    score=1.0,
)


def render(rate: float | None = None, **overrides: object) -> str:
    b = breakdown(**overrides)
    return render_markdown(
        enrich(b, weekly_capacity_hours=30, hourly_rate=rate), check_grounding(b, TRANSCRIPT)
    )


def test_brief_headings_and_total() -> None:
    md = render()
    assert md.startswith("## Estimation: Yoga booking")
    assert "### Task breakdown" in md
    assert "**Total estimated: 41.0 hours**" in md


def test_rendered_total_matches_computed_total() -> None:
    enriched = enrich(
        breakdown(tasks=[task(hours=(3, 7, 20))]), weekly_capacity_hours=30, hourly_rate=None
    )
    md = render_markdown(enriched, GROUNDED)
    assert f"**Total estimated: {enriched.totals.expected_hours:.1f} hours**" in md


def test_sections_present() -> None:
    md = render(rate=50)
    for heading in (
        "### Requirements",
        "### Team",
        "### Duration",
        "### Cost",
        "### Assumptions",
        "### Risks",
        "### Open questions",
    ):
        assert heading in md
    assert "Grounding warnings" not in md
    assert "⚠" not in md


def test_cost_section_omitted_without_rate() -> None:
    assert "### Cost" not in render()


def test_ungrounded_items_marked() -> None:
    md = render(
        requirements=[
            {"id": "R1", "statement": "Booking", "evidence": "a booking app"},
            {"id": "R3", "statement": "Loyalty", "evidence": "invented quote"},
        ],
        tasks=[task("T1", basis=["R1"]), task("T2", basis=["R9"])],
    )
    assert "⚠ **R3**" in md
    assert "| ⚠ T2 |" in md
    warnings = md.split("### Grounding warnings", 1)[1]
    assert "R3" in warnings and "T2" in warnings


def test_table_cells_escape_pipes() -> None:
    md = render(tasks=[task(basis=["R1", "R|2"])])
    [row] = [line for line in md.splitlines() if line.startswith("| ") and "T1" in line]
    assert row.endswith("| R1, R\\|2 |")
    assert len(re.findall(r"(?<!\\)\|", row)) == 9  # 8 cells
