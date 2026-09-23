from app.schemas.estimation import EnrichedBreakdown, GroundingReport

WARN = "⚠"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _hours(value: float) -> str:
    return f"{value:.1f}"


def mark(flagged: bool) -> str:
    return f"{WARN} " if flagged else ""


def render_markdown(b: EnrichedBreakdown, grounding: GroundingReport) -> str:
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
        "| ID | Phase | Task | Optimistic | Likely | Pessimistic | Expected | Basis |",
        "|---|---|---|---:|---:|---:|---:|---|",
        *(
            f"| {mark(task.id in bad_basis)}{task.id} | {task.phase} | {_cell(task.name)} "
            f"| {_hours(task.optimistic_hours)} | {_hours(task.likely_hours)} "
            f"| {_hours(task.pessimistic_hours)} | {_hours(task.expected_hours)} "
            f"| {', '.join(task.basis)} |"
            for task in b.tasks
        ),
        "",
        f"**Total estimated: {_hours(t.expected_hours)} hours** "
        f"(range {_hours(t.optimistic_hours)}–{_hours(t.pessimistic_hours)} h)",
        "",
        "### Team",
        *(f"- {m.count}× {m.role}" for m in b.team),
        "",
        "### Duration",
        f"{t.duration_weeks_min:g}–{t.duration_weeks_max:g} weeks "
        f"(team of {t.team_size}, {t.weekly_capacity_hours:g} h/week per person)",
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
