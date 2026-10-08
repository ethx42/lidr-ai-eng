import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema
from starlette.datastructures import Headers
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.attachments.extractor import AttachmentError
from app.config import Settings, get_settings
from app.observability import configure_logging, request_id_var
from app.prompts.loader import DEFAULT_PARAMS, available_versions, render_estimation_prompt
from app.routers import estimations, sessions
from app.schemas.estimation import EstimateRequest
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent
from app.services.cache import ResponseCache, build_cache, cache_scope
from app.services.conversation import ConversationService, SessionBusy, SessionNotFound
from app.services.errors import LLMError
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_provider
from app.sessions import InMemorySessionStore, SessionsFull

logger = logging.getLogger(__name__)

SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

DESCRIPTION = """\
Turns a meeting transcription into a software estimation using Cache-Augmented Generation:
reference estimations travel inside a cache-stable system prompt, the LLM returns a structured
breakdown, and totals, grounding checks, and the markdown report are computed in code.
"""

# SSE payloads are not route models, so FastAPI would leave them out of the contract. Dumped
# with exclude_none like FastAPI's own schemas, so the whole contract follows one convention.
STREAM_EVENT_SCHEMAS: dict[str, Any] = jsonable_encoder(  # JSON Schema objects by model name
    models_json_schema(
        [(model, "serialization") for model in (StatusEvent, PartialEvent, ErrorEvent)],
        ref_template="#/components/schemas/{model}",
    )[1]["$defs"],
    exclude_none=True,
)


def check_prompts(version: str) -> None:
    """Fail at startup, not on the first request: an unknown PROMPT_VERSION, or any version whose
    templates do not render (StrictUndefined, syntax)."""
    versions = available_versions()
    if version not in versions:
        raise ValueError(f"PROMPT_VERSION={version!r} is unknown; available: {', '.join(versions)}")
    placeholder = EstimateRequest(
        transcription="Startup check.",
        project_type=DEFAULT_PARAMS.project_type,
        detail_level=DEFAULT_PARAMS.detail_level,
        output_format=DEFAULT_PARAMS.output_format,
    )
    for each in versions:
        render_estimation_prompt(placeholder, each)


def error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, **extra},
        "request_id": request_id_var.get(),
    }


class RequestIdMiddleware:
    """Propagates X-Request-ID and turns unhandled errors into a JSON 500 carrying it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("unhandled_error", extra={"request_id": request_id})
            if started:
                raise
            response = JSONResponse(error_body("internal_error", "Internal server error."), 500)
            await response(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class AllowedHostMiddleware:
    """Answers only a Host whose name is in ALLOWED_HOSTS, so a page that rebinds its own name to
    127.0.0.1 (DNS rebinding) cannot call the loopback-published API. Matches like Starlette's
    TrustedHostMiddleware (port ignored), but reads the settings the lifespan resolved and answers
    with the API's error body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings: Settings = scope["app"].state.settings
        host = Headers(scope=scope).get("host", "").split(":")[0].lower()
        if host in settings.allowed_hosts:
            await self.app(scope, receive, send)
            return
        logger.warning("host_rejected", extra={"fields": {"host": host}})
        response = JSONResponse(error_body("invalid_host", "Invalid host header."), 400)
        await response(scope, receive, send)


class BodyLimitMiddleware:
    """Starlette's RequestBodyLimitMiddleware, sized from the settings the lifespan resolved: a
    turn's largest upload plus 1 MiB for the form fields. Its 413 body is plain text, not the
    API's error shape (FastAPI's `{"detail"}` JSON for a chunked body)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings: Settings = scope["app"].state.settings
        limit = settings.attachment_max_files * settings.attachment_max_bytes + 1024 * 1024
        await RequestBodyLimitMiddleware(self.app, max_body_size=limit)(scope, receive, send)


def build_services(
    settings: Settings, provider: LLMProvider, cache: ResponseCache
) -> tuple[EstimationService, ConversationService]:
    """The single-shot and the session services as the API wires them; the live session check
    (`scripts/smoke_live_session.py`) builds its session the same way."""
    estimation = EstimationService(
        provider=provider,
        prompt_version=settings.prompt_version,
        weekly_capacity_hours=settings.weekly_capacity_hours,
        hourly_rate=settings.blended_hourly_rate,
        cache=cache,
        cache_scope=cache_scope(settings),
    )
    conversation = ConversationService(
        estimation=estimation,
        store=InMemorySessionStore(
            max_turns=settings.max_turns,
            max_history_chars=settings.max_history_chars,
            ttl_seconds=settings.session_ttl_seconds,
            max_sessions=settings.max_sessions,
        ),
        limits=settings.attachment_limits,
    )
    return estimation, conversation


def create_app(
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], LLMProvider] = build_provider,
    cache_factory: Callable[[Settings], ResponseCache] = build_cache,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or get_settings()
        configure_logging(resolved.log_level)
        check_prompts(resolved.prompt_version)
        provider = provider_factory(resolved)
        cache = cache_factory(resolved)
        app.state.settings = resolved
        app.state.service, app.state.conversation = build_services(resolved, provider, cache)
        try:
            yield
        finally:
            await provider.aclose()
            await cache.aclose()

    app = FastAPI(
        title="CAG Software Estimator",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(AllowedHostMiddleware)
    app.add_middleware(RequestIdMiddleware)  # outermost: rejections carry the request id too
    app.include_router(estimations.router)
    app.include_router(sessions.router)
    default_openapi = app.openapi

    def openapi() -> dict[str, Any]:  # same signature as FastAPI.openapi
        schema = default_openapi()  # cached on app.openapi_schema; rebuilt when routes change
        schema["components"]["schemas"].update(STREAM_EVENT_SCHEMAS)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented extension hook

    @app.exception_handler(LLMError)
    async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), exc.status_code)

    @app.exception_handler(SessionNotFound)
    async def session_not_found_handler(_: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), 404)

    @app.exception_handler(SessionBusy)
    async def session_busy_handler(_: Request, exc: SessionBusy) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), 409)

    @app.exception_handler(SessionsFull)
    async def sessions_full_handler(_: Request, exc: SessionsFull) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), 503)

    @app.exception_handler(AttachmentError)
    async def attachment_error_handler(_: Request, exc: AttachmentError) -> JSONResponse:
        # No exc_info: a traceback could quote the parser, and the parser the document.
        logger.warning("attachment_rejected", extra={"fields": {"reason": exc.reason}})
        if exc.reason == "busy":
            return JSONResponse(error_body("attachments_busy", str(exc)), 503)
        return JSONResponse(error_body("invalid_attachment", str(exc)), 422)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]
        return JSONResponse(error_body("invalid_request", "Invalid request.", details=details), 422)

    @app.get("/health", tags=["health"])
    async def health(request: Request) -> dict[str, str | list[str]]:
        s: Settings = request.app.state.settings
        (provider, model), *_ = s.chain
        return {
            "status": "ok",
            "version": __version__,
            "environment": s.app_env,
            "provider": provider,
            "model": model,
            "chain": [f"{p}:{m}" for p, m in s.chain],
        }

    return app


app = create_app()
