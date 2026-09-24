import math

from app.schemas.estimation import (
    EnrichedBreakdown,
    EstimatedTask,
    EstimationBreakdown,
    Task,
    Totals,
)


def round_half(value: float) -> float:
    return math.floor(value * 2 + 0.5) / 2


def ceil_half(value: float) -> float:
    return math.ceil(round(value * 2, 6)) / 2


def pert(optimistic: float, likely: float, pessimistic: float) -> float:
    return round_half((optimistic + 4 * likely + pessimistic) / 6)


def expected_hours(task: Task) -> float:
    return pert(task.optimistic_hours, task.likely_hours, task.pessimistic_hours)


def compute_totals(
    breakdown: EstimationBreakdown, *, weekly_capacity_hours: float, hourly_rate: float | None
) -> Totals:
    expected = sum(expected_hours(t) for t in breakdown.tasks)
    optimistic = sum(t.optimistic_hours for t in breakdown.tasks)
    pessimistic = sum(t.pessimistic_hours for t in breakdown.tasks)
    team_size = max(1, sum(m.count for m in breakdown.team))
    weekly_hours = team_size * weekly_capacity_hours
    return Totals(
        expected_hours=expected,
        optimistic_hours=optimistic,
        pessimistic_hours=pessimistic,
        team_size=team_size,
        weekly_capacity_hours=weekly_capacity_hours,
        duration_weeks_min=ceil_half(optimistic / weekly_hours),
        duration_weeks_max=ceil_half(pessimistic / weekly_hours),
        hourly_rate=hourly_rate,
        estimated_cost=round(expected * hourly_rate, 2) if hourly_rate else None,
    )


def enrich(
    breakdown: EstimationBreakdown, *, weekly_capacity_hours: float, hourly_rate: float | None
) -> EnrichedBreakdown:
    tasks = [
        EstimatedTask(**t.model_dump(), expected_hours=expected_hours(t)) for t in breakdown.tasks
    ]
    totals = compute_totals(
        breakdown, weekly_capacity_hours=weekly_capacity_hours, hourly_rate=hourly_rate
    )
    return EnrichedBreakdown(**breakdown.model_dump(exclude={"tasks"}), tasks=tasks, totals=totals)
