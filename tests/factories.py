from typing import Any

from app.prompts.loader import DEFAULT_VERSION
from app.schemas.estimation import (
    CallMetrics,
    EstimateRequest,
    EstimateResponse,
    EstimationBreakdown,
    Usage,
)
from app.services.cache import NullCache, ResponseCache
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.rendering import render_markdown

TRANSCRIPT = (
    "Client: We need a booking app for our “yoga studio”.\n"
    "Client: Customers must pay online with Stripe.\n"
    "PM: Mobile first, launch before summer.\n"
    "Client: The staff should see the bookings for each class and the payments of the day."
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


def team_member(member: tuple[str, int] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(member, tuple):
        role, count = member
        return {"role": role, "count": count}
    return member


def breakdown_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_name": "Yoga booking",
        "summary": "Booking app with online payments.",
        "technologies": ["Stripe"],
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
    if "team" in overrides:
        overrides = overrides | {"team": [team_member(m) for m in overrides["team"]]}
    return data | overrides


def breakdown(**overrides: Any) -> EstimationBreakdown:
    return EstimationBreakdown.model_validate(breakdown_data(**overrides))


REQUEST_DEFAULTS = {
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def request_body(**overrides: object) -> dict[str, object]:
    return {"transcription": TRANSCRIPT, **REQUEST_DEFAULTS, **overrides}


def request(**overrides: object) -> EstimateRequest:
    return EstimateRequest.model_validate(request_body(**overrides))


def typed_request(transcription: str = TRANSCRIPT, **overrides: object) -> EstimateRequest:
    return request(transcription=transcription, **overrides)


def response_fixture() -> EstimateResponse:
    parsed = breakdown()
    enriched = enrich(parsed, weekly_capacity_hours=30, hourly_rate=None)
    grounding = check_grounding(parsed, TRANSCRIPT)
    return EstimateResponse(
        estimation=render_markdown(enriched, grounding),
        breakdown=enriched,
        grounding=grounding,
        model="fake-model",
        provider="openai",
        prompt_version=DEFAULT_VERSION,
        usage=Usage(input_tokens=1200, output_tokens=800),
        metrics=CallMetrics(latency_ms=42),
    )


def make_service(provider: LLMProvider, cache: ResponseCache | None = None) -> EstimationService:
    return EstimationService(
        provider=provider,
        prompt_version=DEFAULT_VERSION,
        weekly_capacity_hours=30,
        hourly_rate=None,
        cache=cache or NullCache(),
        cache_scope="openai:fake-model",
    )
