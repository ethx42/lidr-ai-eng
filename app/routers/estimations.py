import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.config import Settings
from app.context.examples import DENTAL_CLINIC, REFERENCE_ESTIMATIONS
from app.observability import request_id_var
from app.prompts.loader import PROMPT_VERSION
from app.schemas.context import ContextResponse, ReferenceView
from app.schemas.estimation import CallMetrics, EstimateRequest, EstimateResponse, Usage
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent
from app.services.errors import LLMError
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.llm_service import EstimationService
from app.services.pricing import cost_usd
from app.services.rendering import render_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["estimations"])


def get_service(request: Request) -> EstimationService:
    service: EstimationService = request.app.state.service
    return service


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


ServiceDep = Annotated[EstimationService, Depends(get_service)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def checked_request(body: EstimateRequest, settings: SettingsDep) -> EstimateRequest:
    """Length check as a dependency: it runs before a stream starts, so it can still answer 422."""
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
    return body


CheckedRequest = Annotated[EstimateRequest, Depends(checked_request)]


@cache
def example_response() -> dict[str, Any]:
    ref = DENTAL_CLINIC
    # Non-null values throughout: FastAPI drops None from examples, which would hide required keys.
    breakdown = enrich(ref.estimation, weekly_capacity_hours=30, hourly_rate=95)
    grounding = check_grounding(ref.estimation, ref.meeting_summary)
    usage = Usage(
        input_tokens=5600, output_tokens=1400, cached_input_tokens=5120, cache_write_tokens=0
    )
    return EstimateResponse(
        estimation=render_markdown(breakdown, grounding),
        breakdown=breakdown,
        grounding=grounding,
        model="gpt-4o-mini",
        provider="openai",
        prompt_version=PROMPT_VERSION,
        usage=usage,
        metrics=CallMetrics(latency_ms=9800, ttft_ms=1150, cost_usd=cost_usd("gpt-4o-mini", usage)),
    ).model_dump(mode="json")


def error_response(description: str) -> dict[str, Any]:
    return {"description": description}


@router.post(
    "/estimate",
    summary="Estimate a project from a meeting transcription",
    description=(
        "Send the body as JSON with `Content-Type: application/json`; other content types "
        "are rejected with `422 invalid_request`."
    ),
    responses={
        200: {"content": {"application/json": {"example": example_response()}}},
        422: error_response("Invalid request (empty, too long, or unknown fields)."),
        429: error_response("Provider rate limit (`upstream_rate_limited`)."),
        502: error_response("Invalid model output or rejected request."),
        503: error_response("Provider timeout, connection failure, or 5xx."),
    },
)
async def estimate(body: CheckedRequest, service: ServiceDep) -> EstimateResponse:
    return await service.estimate(body)


STREAM_EVENT_REFS = [
    {"$ref": f"#/components/schemas/{model.__name__}"}
    for model in (StatusEvent, PartialEvent, EstimateResponse, ErrorEvent)
]
STREAM_DESCRIPTION = """\
Same body as `POST /api/v1/estimate`; validation errors return `422` JSON before the stream
starts. Events: `status` (`StatusEvent`, any number), `partial` (`PartialEvent`; its `seq` is
also the SSE `id`), then exactly one terminal event: `result` (`EstimateResponse`) or `error`
(`ErrorEvent`).
"""


@router.post(
    "/estimate/stream",
    response_class=EventSourceResponse,
    summary="Stream an estimate as Server-Sent Events",
    description=STREAM_DESCRIPTION,
    responses={
        200: {"content": {"text/event-stream": {"schema": {"oneOf": STREAM_EVENT_REFS}}}},
        422: error_response("Invalid request (empty, too long, or unknown fields)."),
    },
)
async def estimate_stream(
    body: CheckedRequest, service: ServiceDep
) -> AsyncIterator[ServerSentEvent]:
    # Errors after the first byte cannot change the 200 status: they become an `error` event.
    try:
        # aclosing: closes the service (and the upstream stream) promptly on disconnect.
        async with aclosing(service.estimate_stream(body)) as items:
            async for item in items:
                match item:
                    case StatusEvent():
                        yield ServerSentEvent(event="status", data=item)
                    case PartialEvent():
                        yield ServerSentEvent(event="partial", data=item, id=str(item.seq))
                    case EstimateResponse():
                        yield ServerSentEvent(event="result", data=item)
    except LLMError as exc:
        yield ServerSentEvent(
            event="error",
            data=ErrorEvent(
                code=exc.code,
                message=exc.message,
                retryable=exc.status_code in (429, 503),
                request_id=request_id_var.get(),
            ),
        )
    except Exception:
        logger.exception("stream_failed")
        yield ServerSentEvent(
            event="error",
            data=ErrorEvent(
                code="internal_error",
                message="Internal server error.",
                retryable=False,
                request_id=request_id_var.get(),
            ),
        )


@router.get("/context", summary="Prompt, reference estimations and limits used for estimates")
async def context(service: ServiceDep, settings: SettingsDep) -> ContextResponse:
    return ContextResponse(
        prompt_version=service.prompt.version,
        system_prompt=service.prompt.system_text,
        references=[
            ReferenceView(
                size=ref.size, meeting_summary=ref.meeting_summary, estimation=ref.estimation
            )
            for ref in REFERENCE_ESTIMATIONS
        ],
        chain=[f"{settings.llm_provider}:{settings.llm_model}"],
        max_transcription_chars=settings.max_transcription_chars,
    )
