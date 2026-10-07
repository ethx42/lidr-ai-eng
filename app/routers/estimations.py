import logging
from collections.abc import AsyncGenerator, AsyncIterator
from functools import cache
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.config import Settings
from app.context.examples import DENTAL_CLINIC, REFERENCE_ESTIMATIONS
from app.observability import request_id_var
from app.prompts.loader import (
    DEFAULT_PARAMS,
    VERSION_PATTERN,
    PromptParams,
    available_versions,
    render_system,
)
from app.schemas.context import ContextResponse, ReferenceView
from app.schemas.estimation import (
    CallMetrics,
    DetailLevel,
    EstimateRequest,
    EstimateResponse,
    OutputFormat,
    ProjectType,
    Usage,
)
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent
from app.services.errors import LLMError
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.llm_service import EstimationService, StreamItem
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
Refresh = Annotated[
    bool,
    Query(description="Skip the cache lookup and regenerate; the fresh result replaces the entry."),
]
PromptVersionQuery = Annotated[
    str | None,
    Query(description="Prompt template version (`v1`, `v2`, …); default: `PROMPT_VERSION`."),
]


def checked_prompt_version(settings: SettingsDep, prompt_version: PromptVersionQuery = None) -> str:
    """The value names a template directory: only a listed version reaches the loader."""
    if prompt_version is None:
        return settings.prompt_version
    versions = available_versions()
    if VERSION_PATTERN.fullmatch(prompt_version) and prompt_version in versions:
        return prompt_version
    raise RequestValidationError(
        [
            {
                "loc": ("query", "prompt_version"),
                "msg": f"Unknown prompt version; available: {', '.join(versions)}.",
                "type": "enum",
            }
        ]
    )


PromptVersionDep = Annotated[str, Depends(checked_prompt_version)]


async def service_stream(
    body: CheckedRequest,
    service: ServiceDep,
    prompt_version: PromptVersionDep,
    refresh: Refresh = False,
) -> AsyncIterator[AsyncGenerator[StreamItem]]:
    """Owns the service stream's lifetime. FastAPI iterates the endpoint generator in a producer
    task that it cancels but never closes: when a slow reader disconnects, that task is cancelled
    on a full buffer while both generators sit at a `yield`. This request-scoped teardown runs
    after that cancellation, in the request's context, so the upstream stream closes (and the
    call is logged with its request id) now instead of at garbage collection."""
    items = service.estimate_stream(body, refresh=refresh, prompt_version=prompt_version)
    try:
        yield items
    except* anyio.BrokenResourceError:
        # FastAPI's SSE keep-alive task was parked sending to the stream it has just closed: a
        # client that left mid-send, not a server fault.
        logger.info("client_disconnected")
    finally:
        with anyio.move_on_after(1, shield=True):  # bounded, and immune to the request's cancel
            await items.aclose()


ServiceStream = Annotated[AsyncGenerator[StreamItem], Depends(service_stream)]


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
        # The code default, never the environment the contract is exported from.
        prompt_version=Settings.model_fields["prompt_version"].default,
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
        422: error_response(
            "Invalid request (empty, too long, unknown fields, or unknown prompt version)."
        ),
        429: error_response("Provider rate limit (`upstream_rate_limited`)."),
        502: error_response("Invalid model output or rejected request."),
        503: error_response("Provider timeout, connection failure, or 5xx."),
    },
)
async def estimate(
    body: CheckedRequest,
    service: ServiceDep,
    prompt_version: PromptVersionDep,
    refresh: Refresh = False,
) -> EstimateResponse:
    return await service.estimate(body, refresh=refresh, prompt_version=prompt_version)


STREAM_EVENT_REFS = [
    {"$ref": f"#/components/schemas/{model.__name__}"}
    for model in (StatusEvent, PartialEvent, EstimateResponse, ErrorEvent)
]
STREAM_DESCRIPTION = """\
Same body and query as `POST /api/v1/estimate`; validation errors return `422` JSON before the
stream starts. Events: `status` (`StatusEvent`, any number), `partial` (`PartialEvent`; its `seq`
is also the SSE `id`), then exactly one terminal event: `result` (`EstimateResponse`) or `error`
(`ErrorEvent`).
"""


@router.post(
    "/estimate/stream",
    response_class=EventSourceResponse,
    summary="Stream an estimate as Server-Sent Events",
    description=STREAM_DESCRIPTION,
    responses={
        200: {"content": {"text/event-stream": {"schema": {"oneOf": STREAM_EVENT_REFS}}}},
        422: error_response(
            "Invalid request (empty, too long, unknown fields, or unknown prompt version)."
        ),
    },
)
async def estimate_stream(items: ServiceStream) -> AsyncIterator[ServerSentEvent]:
    # Errors after the first byte cannot change the 200 status: they become an `error` event.
    try:
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


@router.get(
    "/context",
    summary="Prompt, reference estimations and limits used for estimates",
    description=(
        "The system prompt is rendered for the given enums (defaults: `web_saas`, `medium`, "
        "`phases_table`) and prompt version (default: the `PROMPT_VERSION` setting)."
    ),
    responses={422: error_response("Unknown enum value or prompt version.")},
)
async def context(
    settings: SettingsDep,
    prompt_version: PromptVersionDep,
    project_type: ProjectType = DEFAULT_PARAMS.project_type,
    detail_level: DetailLevel = DEFAULT_PARAMS.detail_level,
    output_format: OutputFormat = DEFAULT_PARAMS.output_format,
) -> ContextResponse:
    params = PromptParams(project_type, detail_level, output_format)
    return ContextResponse(
        prompt_version=prompt_version,
        available_versions=available_versions(),
        system_prompt=render_system(params, prompt_version),
        references=[
            ReferenceView(
                size=ref.size, meeting_summary=ref.meeting_summary, estimation=ref.estimation
            )
            for ref in REFERENCE_ESTIMATIONS
        ],
        chain=[f"{provider}:{model}" for provider, model in settings.chain],
        max_transcription_chars=settings.max_transcription_chars,
    )
