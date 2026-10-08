"""Conversational sessions. A turn is a multipart form: the transcript, the three prompt enums and
up to `ATTACHMENT_MAX_FILES` attachments. Every check runs in the `prepared_turn` dependency,
before a stream can start; once one has, the status is 200 and failures become `error` events."""

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from app.attachments.extractor import (
    Attachment,
    AttachmentError,
    ExtractedAttachment,
    megabytes,
    sanitise_name,
)
from app.attachments.limits import AttachmentLimits
from app.config import Settings
from app.observability import request_id_var
from app.routers.estimations import SettingsDep, check_transcript_length, error_response
from app.schemas.estimation import (
    MAX_LANGUAGE_CHARS,
    DetailLevel,
    EstimateRequest,
    OutputFormat,
    ProjectType,
)
from app.schemas.session import SessionCreated, SessionView, TurnResponse
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent
from app.services.conversation import ConversationService, SessionBusy, SessionNotFound
from app.services.errors import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

TurnItem = StatusEvent | PartialEvent | TurnResponse


def get_conversation(request: Request) -> ConversationService:
    conversation: ConversationService = request.app.state.conversation
    return conversation


ConversationDep = Annotated[ConversationService, Depends(get_conversation)]


def single_line_breaks(value: object) -> object:
    """Multipart sends every line break of a form field as CRLF (browsers and undici alike), while
    the composer counts a line break as one character: normalise before any length check."""
    return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


LineBreaks = BeforeValidator(single_line_breaks)


# One model for the fields and the files: a separate `Form()`/`File()` param next to a form model
# makes FastAPI expect the model embedded under its name (422).
class SessionEstimateForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1), LineBreaks
    ] = Field(description="This turn's meeting transcription. Treated strictly as data.")
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    output_language: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_LANGUAGE_CHARS)]
        | None,
        LineBreaks,
    ] = Field(
        default=None,
        description=(
            f"At most {MAX_LANGUAGE_CHARS} characters. Empty means not given: the "
            "transcription's language."
        ),
    )
    attachments: list[UploadFile] = Field(
        default=[], description="PDF, DOCX or plain text. Empty file inputs are ignored."
    )


@dataclass(frozen=True)
class PreparedTurn:
    session_id: str
    request: EstimateRequest
    attachments: list[ExtractedAttachment]


def ensure_idle(conversation: ConversationService, session_id: str) -> None:
    if conversation.get(session_id).lock.locked():
        raise SessionBusy(session_id)


def estimate_request(form: SessionEstimateForm, settings: Settings) -> EstimateRequest:
    """The single-shot request and length check, so both paths accept the same transcripts."""
    check_transcript_length(form.transcript, "transcript", settings)
    try:
        return EstimateRequest(
            transcription=form.transcript,
            project_type=form.project_type,
            detail_level=form.detail_level,
            output_format=form.output_format,
            output_language=form.output_language or None,
        )
    except ValidationError as exc:  # the form mirrors these constraints; a drift is still a 422
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        ) from exc


async def read_attachments(uploads: list[UploadFile], limits: AttachmentLimits) -> list[Attachment]:
    """Drops empty browser file inputs, then checks the count and each size before reading."""
    files = [(f.filename, f) for f in uploads if f.filename and f.size]
    if len(files) > limits.max_files:
        raise AttachmentError(f"too many attachments (at most {limits.max_files} per turn)")
    read: list[Attachment] = []
    for name, file in files:
        # `size` is what the parser wrote; the bounded read holds even if it were wrong.
        fits = (file.size or 0) <= limits.max_bytes
        data = await file.read(limits.max_bytes + 1) if fits else None
        if data is None or len(data) > limits.max_bytes:
            raise AttachmentError(
                f"{sanitise_name(name)}: larger than {megabytes(limits.max_bytes)}"
            )
        read.append(Attachment(name, data))
    return read


async def prepared_turn(
    session_id: str,
    form: Annotated[SessionEstimateForm, Form(media_type="multipart/form-data")],
    conversation: ConversationDep,
    settings: SettingsDep,
) -> PreparedTurn:
    ensure_idle(conversation, session_id)
    request = estimate_request(form, settings)
    files = await read_attachments(form.attachments, conversation.limits)
    extracted = await conversation.extract(files) if files else []
    ensure_idle(conversation, session_id)  # extraction can take seconds
    return PreparedTurn(session_id, request, extracted)


PreparedTurnDep = Annotated[PreparedTurn, Depends(prepared_turn)]


async def turn_stream(
    turn: PreparedTurnDep, conversation: ConversationDep
) -> AsyncIterator[AsyncGenerator[TurnItem]]:
    """Owns the turn stream's lifetime, like `estimations.service_stream` (which explains why).
    Here it also frees the session: a turn left parked at a `yield` would hold its lock, making
    every later turn a 409, until garbage collection."""
    items = conversation.turn_stream(turn.session_id, turn.request, turn.attachments)
    try:
        yield items
    except* anyio.BrokenResourceError:
        logger.info("client_disconnected")
    finally:
        with anyio.move_on_after(1, shield=True):  # bounded, and immune to the request's cancel
            await items.aclose()


TurnStream = Annotated[AsyncGenerator[TurnItem], Depends(turn_stream)]

TURN_DESCRIPTION = """\
A `multipart/form-data` body: `transcript`, `project_type`, `detail_level`, `output_format`, an
optional `output_language`, and up to `ATTACHMENT_MAX_FILES` `attachments` (PDF, DOCX or plain
text, `ATTACHMENT_MAX_BYTES` each). Their text joins the turn's prompt. Turns never use the
response cache. A body over `ATTACHMENT_MAX_FILES` × `ATTACHMENT_MAX_BYTES` + 1 MiB gets a `413`
whose body is not the JSON error shape.
"""
TURN_ERRORS: dict[int | str, dict[str, Any]] = {  # Any: OpenAPI response objects are JSON
    404: error_response("Unknown, expired or evicted session (`session_not_found`)."),
    409: error_response("Another turn of this session is in progress (`session_busy`)."),
    413: error_response("Body too large (plain text, not the JSON error shape)."),
    422: error_response(
        "Invalid field or transcript too long (`invalid_request`), or an attachment that is "
        "unsupported, unreadable, too large or one too many (`invalid_attachment`; the message "
        "names the file)."
    ),
    503: error_response("No free attachment reader (`attachments_busy`); try again."),
}


@router.post(
    "",
    status_code=201,
    summary="Start a conversational estimation session",
    responses={
        503: error_response("At the session cap with every session mid-turn (`sessions_full`).")
    },
)
async def create_session(conversation: ConversationDep) -> SessionCreated:
    return SessionCreated(session_id=conversation.start().id)


@router.get(
    "/{session_id}",
    summary="What a session knows so far",
    responses={404: TURN_ERRORS[404]},
)
async def get_session(
    session_id: str, conversation: ConversationDep, settings: SettingsDep
) -> SessionView:
    session = conversation.get(session_id)
    return SessionView(
        session_id=session.id,
        project_metadata=session.metadata,
        history_turns=session.history.turns,
        max_turns=settings.max_turns,
        prompt_version=conversation.prompt_version,
    )


@router.post(
    "/{session_id}/estimate",
    summary="Estimate one turn of a session",
    description=TURN_DESCRIPTION,
    responses={
        **TURN_ERRORS,
        429: error_response("Provider rate limit (`upstream_rate_limited`)."),
        502: error_response("Invalid model output or rejected request."),
        503: error_response(
            "Provider timeout, connection failure or 5xx, or no free attachment reader "
            "(`attachments_busy`)."
        ),
    },
)
async def estimate(turn: PreparedTurnDep, conversation: ConversationDep) -> TurnResponse:
    return await conversation.turn(turn.session_id, turn.request, turn.attachments)


TURN_EVENT_REFS = [
    {"$ref": f"#/components/schemas/{model.__name__}"}
    for model in (StatusEvent, PartialEvent, TurnResponse, ErrorEvent)
]


def error_event(code: str, message: str, *, retryable: bool) -> ServerSentEvent:
    return ServerSentEvent(
        event="error",
        data=ErrorEvent(
            code=code, message=message, retryable=retryable, request_id=request_id_var.get()
        ),
    )


@router.post(
    "/{session_id}/estimate/stream",
    response_class=EventSourceResponse,
    summary="Stream one turn of a session as Server-Sent Events",
    description=TURN_DESCRIPTION
    + "\nEvery error above is JSON, sent before the stream starts. Events: `status`, `partial` "
    "(its `seq` is also the SSE `id`), then exactly one terminal event: `result` "
    "(`TurnResponse`) or `error` (`ErrorEvent`). The session changes only with a `result`.\n",
    responses={
        200: {"content": {"text/event-stream": {"schema": {"oneOf": TURN_EVENT_REFS}}}},
        **TURN_ERRORS,
    },
)
async def estimate_stream(items: TurnStream) -> AsyncIterator[ServerSentEvent]:
    try:
        async for item in items:
            match item:
                case StatusEvent():
                    yield ServerSentEvent(event="status", data=item)
                case PartialEvent():
                    yield ServerSentEvent(event="partial", data=item, id=str(item.seq))
                case TurnResponse():
                    yield ServerSentEvent(event="result", data=item)
    except (SessionBusy, SessionNotFound) as exc:
        # Lost after the checks: another turn took the session, or the cap evicted it.
        yield error_event(exc.code, exc.message, retryable=isinstance(exc, SessionBusy))
    except LLMError as exc:
        yield error_event(exc.code, exc.message, retryable=exc.status_code in (429, 503))
    except Exception:
        logger.exception("stream_failed")
        yield error_event("internal_error", "Internal server error.", retryable=False)
