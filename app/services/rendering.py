from collections.abc import Callable, Sequence

from app.schemas.estimation import (
    EnrichedBreakdown,
    EstimatedTask,
    GroundingReport,
    OutputFormat,
    Phase,
)

WARN = "⚠"
# In delivery order, which phase rollups and narrative paragraphs follow.
PHASE_LABELS: dict[Phase, str] = {
    "discovery": "Discovery",
    "ux_ui": "UX/UI",
    "backend": "Backend",
    "frontend": "Frontend",
    "integrations": "Integrations",
    "qa": "QA",
    "devops": "DevOps",
    "project_management": "Project management",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _hours(value: float) -> str:
    return f"{value:.1f}"


def _inline(text: str) -> str:
    return " ".join(text.split())


def mark(flagged: bool) -> str:
    return f"{WARN} " if flagged else ""


def _by_phase(tasks: Sequence[EstimatedTask]) -> list[tuple[Phase, list[EstimatedTask]]]:
    return [(p, group) for p in PHASE_LABELS if (group := [t for t in tasks if t.phase == p])]


def _expected(tasks: Sequence[EstimatedTask]) -> float:
    return sum(t.expected_hours for t in tasks)


def _range(tasks: Sequence[EstimatedTask]) -> str:
    low, high = sum(t.optimistic_hours for t in tasks), sum(t.pessimistic_hours for t in tasks)
    return f"{_hours(low)}–{_hours(high)}"


def _line_items(b: EnrichedBreakdown, bad_basis: set[str]) -> list[str]:
    return [
        "| ID | Phase | Task | Optimistic | Likely | Pessimistic | Expected | Basis |",
        "|---|---|---|---:|---:|---:|---:|---|",
        *(
            f"| {mark(task.id in bad_basis)}{task.id} | {task.phase} | {_cell(task.name)} "
            f"| {_hours(task.optimistic_hours)} | {_hours(task.likely_hours)} "
            f"| {_hours(task.pessimistic_hours)} | {_hours(task.expected_hours)} "
            f"| {_cell(', '.join(task.basis))} |"
            for task in b.tasks
        ),
    ]


def _phases_table(b: EnrichedBreakdown, bad_basis: set[str]) -> list[str]:
    rate = b.totals.hourly_rate if b.totals.estimated_cost is not None else None

    def row(phase: Phase, group: list[EstimatedTask]) -> str:
        expected, flag = _expected(group), mark(any(t.id in bad_basis for t in group))
        cells = f"| {flag}{phase} | {len(group)} | {_hours(expected)} | {_range(group)} |"
        return cells if rate is None else f"{cells} {expected * rate:,.2f} |"

    return [
        "| Phase | Tasks | Expected h | Range h |" + ("" if rate is None else " Cost |"),
        "|---|---:|---:|---:|" + ("" if rate is None else "---:|"),
        *(row(phase, group) for phase, group in _by_phase(b.tasks)),
    ]


def _narrative(b: EnrichedBreakdown, bad_basis: set[str]) -> list[str]:
    def paragraph(phase: Phase, group: list[EstimatedTask]) -> str:
        count = f"{len(group)} task{'' if len(group) == 1 else 's'}"
        lead = (
            f"**{PHASE_LABELS[phase]}** — {count}, {_hours(_expected(group))} h expected "
            f"({_range(group)} h)."
        )
        tasks = (
            f"{mark(t.id in bad_basis)}{t.id} {_inline(t.name)}: {_inline(t.rationale)}"
            for t in group
        )
        return " ".join([lead, *tasks])

    return ["\n\n".join(paragraph(phase, group) for phase, group in _by_phase(b.tasks))]


LAYOUTS: dict[OutputFormat, Callable[[EnrichedBreakdown, set[str]], list[str]]] = {
    OutputFormat.PHASES_TABLE: _phases_table,
    OutputFormat.LINE_ITEMS: _line_items,
    OutputFormat.NARRATIVE: _narrative,
}


def render_markdown(
    b: EnrichedBreakdown, grounding: GroundingReport, layout: OutputFormat = OutputFormat.LINE_ITEMS
) -> str:
    ungrounded = set(grounding.ungrounded_requirement_ids)
    bad_basis = set(grounding.tasks_without_valid_basis)
    t = b.totals

    lines = [
        f"## Estimation: {b.project_name}",
        "",
        b.summary,
        "",
        f"**Confidence:** {b.confidence} — {b.confidence_rationale}",
        "",
        "### Requirements",
        *(
            f'- {mark(r.id in ungrounded)}**{r.id}** {r.statement} — _"{r.evidence}"_'
            for r in b.requirements
        ),
        "",
        "### Task breakdown",
        "",
        *LAYOUTS[layout](b, bad_basis),
        "",
        (
            f"**Total estimated: {_hours(t.expected_hours)} hours** "
            f"(range {_hours(t.optimistic_hours)}–{_hours(t.pessimistic_hours)} h)"
        ),
        "",
        "### Team",
        *(f"- {m.count}× {m.role}" for m in b.team),
        "",
        "### Duration",
        (
            f"{t.duration_weeks_min:g}–{t.duration_weeks_max:g} weeks "
            f"(team of {t.team_size}, {t.weekly_capacity_hours:g} h/week per person)"
        ),
    ]
    if t.estimated_cost is not None and t.hourly_rate is not None:
        lines += ["", "### Cost", f"{t.estimated_cost:,.2f} at {t.hourly_rate:g}/h blended rate"]
    lines += [
        "",
        "### Assumptions",
        *(f"- **{a.id}** {a.statement} _(if wrong: {a.impact_if_wrong})_" for a in b.assumptions),
        "",
        "### Risks",
        *(f"- [{r.impact}] {r.description} — {r.mitigation}" for r in b.risks),
        "",
        "### Open questions",
        *(f"- {q}" for q in b.open_questions),
    ]
    if ungrounded or bad_basis:
        lines += ["", "### Grounding warnings"]
        lines += [
            f"- {WARN} {rid}: evidence not found in the transcript"
            for rid in grounding.ungrounded_requirement_ids
        ]
        lines += [
            f"- {WARN} {tid}: basis cites unknown or no requirements/assumptions"
            for tid in grounding.tasks_without_valid_basis
        ]
    return "\n".join(lines) + "\n"


def render_compact(b: EnrichedBreakdown) -> str:
    """The assistant turn kept in a session's history: what the next turn must stay consistent
    with, a fraction of the JSON's size. One line per fact, so model text cannot forge a line."""
    t = b.totals
    return "\n".join(
        [
            f"Project: {_inline(b.project_name)}",
            f"Summary: {_inline(b.summary)}",
            "Tasks:",
            *(
                f"{task.id} [{task.phase}] {_inline(task.name)} — "
                f"{_hours(task.likely_hours)} h likely"
                for task in b.tasks
            ),
            (
                f"Total: {_hours(t.expected_hours)} h expected "
                f"(range {_hours(t.optimistic_hours)}–{_hours(t.pessimistic_hours)} h), "
                f"team of {t.team_size}"
            ),
            "Open questions:",
            *(f"- {_inline(q)}" for q in b.open_questions),
        ]
    )
