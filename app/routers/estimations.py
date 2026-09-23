from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError

from app.config import Settings
from app.context.examples import DENTAL_CLINIC
from app.prompts.loader import PROMPT_VERSION
from app.schemas.estimation import EstimateRequest, EstimateResponse, Usage
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.llm_service import EstimationService
from app.services.rendering import render_markdown

router = APIRouter(prefix="/api/v1", tags=["estimations"])


def get_service(request: Request) -> EstimationService:
    service: EstimationService = request.app.state.service
    return service


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@cache
def example_response() -> dict[str, Any]:
    ref = DENTAL_CLINIC
    breakdown = enrich(ref.estimation, weekly_capacity_hours=30, hourly_rate=None)
    grounding = check_grounding(ref.estimation, ref.meeting_summary)
    return EstimateResponse(
        estimation=render_markdown(breakdown, grounding),
        breakdown=breakdown,
        grounding=grounding,
        model="gpt-4o-mini",
        provider="openai",
        prompt_version=PROMPT_VERSION,
        usage=Usage(input_tokens=5600, output_tokens=1400, cached_input_tokens=5120),
    ).model_dump(mode="json")


def error_response(description: str) -> dict[str, Any]:
    return {"description": description}


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    summary="Estimate a project from a meeting transcription",
    responses={
        200: {"content": {"application/json": {"example": example_response()}}},
        422: error_response("Invalid request (empty, too long, or unknown fields)."),
        429: error_response("Provider rate limit (`upstream_rate_limited`)."),
        502: error_response("Invalid model output or rejected request."),
        503: error_response("Provider timeout, connection failure, or 5xx."),
    },
)
async def estimate(
    body: EstimateRequest,
    service: Annotated[EstimationService, Depends(get_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> EstimateResponse:
    limit = settings.max_transcription_chars
    if len(body.transcription) > limit:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "transcription"),
                    "msg": f"Transcription exceeds {limit} characters.",
                    "type": "string_too_long",
                }
            ]
        )
    return await service.estimate(body)
