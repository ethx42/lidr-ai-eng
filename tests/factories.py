from typing import Any

from app.schemas.estimation import EstimationBreakdown

TRANSCRIPT = (
    "Client: We need a booking app for our “yoga studio”.\n"
    "Client: Customers must pay online with Stripe.\n"
    "PM: Mobile first, launch before summer."
)


def task(
    id: str = "T1",
    hours: tuple[float, float, float] = (8, 10, 18),
    basis: list[str] | None = None,
    phase: str = "backend",
) -> dict[str, Any]:
    o, m, p = hours
    return {
        "id": id,
        "phase": phase,
        "name": f"Task {id}",
        "rationale": "Needed for the booking flow.",
        "basis": basis if basis is not None else ["R1"],
        "optimistic_hours": o,
        "likely_hours": m,
        "pessimistic_hours": p,
    }


def breakdown_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_name": "Yoga booking",
        "summary": "Booking app with online payments.",
        "requirements": [
            {"id": "R1", "statement": "Online booking", "evidence": "a booking app"},
            {"id": "R2", "statement": "Stripe payments", "evidence": "pay online with Stripe"},
        ],
        "assumptions": [
            {"id": "A1", "statement": "Single studio", "impact_if_wrong": "Multi-tenant work"},
        ],
        "open_questions": ["Which calendar system is in use?"],
        "tasks": [
            task("T1", (8, 10, 18), ["R1"]),
            task("T2", (20, 30, 40), ["R2", "A1"], phase="qa"),
        ],
        "team": [{"role": "Full-stack developer", "count": 2}],
        "risks": [
            {
                "description": "Stripe onboarding delay",
                "impact": "medium",
                "mitigation": "Start early",
            }
        ],
        "confidence": "medium",
        "confidence_rationale": "Scope is clear but integrations are unknown.",
    }
    return data | overrides


def breakdown(**overrides: Any) -> EstimationBreakdown:
    return EstimationBreakdown.model_validate(breakdown_data(**overrides))
