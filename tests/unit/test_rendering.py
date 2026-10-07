import re
from typing import get_args

import pytest

from app.schemas.estimation import EnrichedBreakdown, GroundingReport, OutputFormat, Phase
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.rendering import PHASE_LABELS, render_markdown
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


ENRICHED = enrich(breakdown(), weekly_capacity_hours=30, hourly_rate=None)  # T1 backend, T2 qa


def test_phases_table_rolls_up_by_phase() -> None:
    md = render_markdown(ENRICHED, GROUNDED, OutputFormat.PHASES_TABLE)
    assert "| Phase | Tasks | Expected h | Range h |" in md
    backend = [t for t in ENRICHED.tasks if t.phase == "backend"]
    assert f"| backend | {len(backend)} |" in md


def test_narrative_has_no_tables() -> None:
    md = render_markdown(ENRICHED, GROUNDED, OutputFormat.NARRATIVE)
    assert "|---" not in md
    assert "**Backend**" in md


def test_line_items_is_the_default_layout() -> None:
    assert render_markdown(ENRICHED, GROUNDED) == render_markdown(
        ENRICHED, GROUNDED, OutputFormat.LINE_ITEMS
    )


def phased(rate: float | None = None) -> EnrichedBreakdown:
    tasks = [
        task("T1", (8, 10, 18), phase="backend"),
        task("T2", (20, 30, 40), phase="qa"),
        task("T3", (3, 7, 20), phase="backend"),
        task("T4", (2, 4, 6), phase="discovery"),
    ]
    return enrich(breakdown(tasks=tasks), weekly_capacity_hours=30, hourly_rate=rate)


def test_phases_table_sums_each_phase_in_delivery_order() -> None:
    md = render_markdown(phased(), GROUNDED, OutputFormat.PHASES_TABLE)
    rows = [line for line in md.splitlines() if line.startswith("| ") and "Phase" not in line]
    assert rows == [
        "| discovery | 1 | 4.0 | 2.0–6.0 |",
        "| backend | 2 | 19.5 | 11.0–38.0 |",
        "| qa | 1 | 30.0 | 20.0–40.0 |",
    ]
    assert "**Total estimated: 53.5 hours**" in md
    assert "| T1 |" not in md


def test_phases_table_cost_column_only_with_a_rate() -> None:
    assert "Cost |" not in render_markdown(phased(), GROUNDED, OutputFormat.PHASES_TABLE)
    md = render_markdown(phased(rate=100), GROUNDED, OutputFormat.PHASES_TABLE)
    assert "| Phase | Tasks | Expected h | Range h | Cost |" in md
    assert "| backend | 2 | 19.5 | 11.0–38.0 | 1,950.00 |" in md
    assert "### Cost" in md


def test_every_phase_has_a_label() -> None:
    assert list(PHASE_LABELS) == list(get_args(Phase))


def test_narrative_writes_one_paragraph_per_phase() -> None:
    md = render_markdown(phased(), GROUNDED, OutputFormat.NARRATIVE)
    assert (
        "**Backend** — 2 tasks, 19.5 h expected (11.0–38.0 h). "
        "T1 Task T1: Needed for the booking flow. T3 Task T3: Needed for the booking flow.\n"
    ) in md
    assert "**QA** — 1 task, 30.0 h expected (20.0–40.0 h). T2 Task T2:" in md
    assert md.index("**Discovery**") < md.index("**Backend**") < md.index("**QA**")


def test_narrative_keeps_each_phase_in_one_paragraph() -> None:
    multiline = task() | {"rationale": "First line.\n\n| not | a table |\nSecond line."}
    md = render_markdown(
        enrich(breakdown(tasks=[multiline]), weekly_capacity_hours=30, hourly_rate=None),
        GROUNDED,
        OutputFormat.NARRATIVE,
    )
    assert "T1 Task T1: First line. | not | a table | Second line.\n" in md


@pytest.mark.parametrize("layout", list(OutputFormat))
def test_grounding_marks_appear_in_every_layout(layout: OutputFormat) -> None:
    b = breakdown(
        requirements=[
            {"id": "R1", "statement": "Booking", "evidence": "a booking app"},
            {"id": "R3", "statement": "Loyalty", "evidence": "invented quote"},
        ],
        tasks=[task("T1", basis=["R1"]), task("T2", basis=["R9"], phase="qa")],
    )
    md = render_markdown(
        enrich(b, weekly_capacity_hours=30, hourly_rate=None),
        check_grounding(b, TRANSCRIPT),
        layout,
    )
    assert "⚠ **R3**" in md
    breakdown_section = md.split("### Task breakdown", 1)[1].split("**Total estimated", 1)[0]
    flagged = {
        OutputFormat.LINE_ITEMS: "| ⚠ T2 |",
        OutputFormat.PHASES_TABLE: "| ⚠ qa | 1 |",
        OutputFormat.NARRATIVE: "⚠ T2 Task T2:",
    }[layout]
    assert flagged in breakdown_section
    assert breakdown_section.count("⚠") == 1
    warnings = md.split("### Grounding warnings", 1)[1]
    assert "R3" in warnings and "T2" in warnings
