import pytest

from app.services.estimation_math import compute_totals, enrich, pert
from tests.factories import breakdown, task


@pytest.mark.parametrize(
    "hours,expected",
    [
        ((8, 10, 18), 11.0),
        ((20, 30, 40), 30.0),
        ((1, 2, 4), 2.0),
        ((1, 1, 2), 1.0),
        ((2, 3, 5), 3.0),
    ],
)
def test_pert_rounds_to_half_hour(hours: tuple[float, float, float], expected: float) -> None:
    assert pert(*hours) == expected


def test_totals_scenario() -> None:
    enriched = enrich(breakdown(), weekly_capacity_hours=30, hourly_rate=None)
    assert [t.expected_hours for t in enriched.tasks] == [11.0, 30.0]
    assert enriched.totals.expected_hours == 41.0
    assert enriched.totals.optimistic_hours == 28.0
    assert enriched.totals.pessimistic_hours == 58.0
    assert enriched.totals.estimated_cost is None


def test_duration_range_from_team_and_capacity() -> None:
    totals = compute_totals(breakdown(), weekly_capacity_hours=10, hourly_rate=None)
    assert totals.team_size == 2
    assert totals.duration_weeks_min == 1.5  # 28 / 20 = 1.4 -> rounded up to 1.5
    assert totals.duration_weeks_max == 3.0  # 58 / 20 = 2.9 -> 3.0


def test_team_size_at_least_one() -> None:
    totals = compute_totals(breakdown(team=[]), weekly_capacity_hours=30, hourly_rate=None)
    assert totals.team_size == 1


def test_cost_when_rate_configured() -> None:
    totals = compute_totals(breakdown(), weekly_capacity_hours=30, hourly_rate=50)
    assert totals.estimated_cost == 2050.0
    assert totals.hourly_rate == 50


def test_model_numbers_are_ignored() -> None:
    enriched = enrich(
        breakdown(tasks=[task(hours=(4, 4, 4))]), weekly_capacity_hours=30, hourly_rate=None
    )
    assert enriched.totals.expected_hours == 4.0
