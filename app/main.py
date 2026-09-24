import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.config import Settings, get_settings
from app.observability import configure_logging, request_id_var
from app.prompts.loader import load_prompt
from app.routers import estimations
from app.services.errors import LLMError
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_provider

logger = logging.getLogger(__name__)

SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

DESCRIPTION = """\
Turns a meeting transcription into a software estimation using Cache-Augmented Generation:
reference estimations travel inside a cache-stable system prompt, the LLM returns a structured
breakdown, and totals, grounding checks, and the markdown report are computed in code.
"""


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


def create_app(
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], LLMProvider] = build_provider,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or get_settings()
        configure_logging(resolved.log_level)
        provider = provider_factory(resolved)
        app.state.settings = resolved
        app.state.service = EstimationService(
            provider=provider,
            prompt=load_prompt(),
            weekly_capacity_hours=resolved.weekly_capacity_hours,
            hourly_rate=resolved.blended_hourly_rate,
        )
        try:
            yield
        finally:
            await provider.aclose()

    app = FastAPI(
        title="CAG Software Estimator",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(estimations.router)

    @app.exception_handler(LLMError)
    async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]
        return JSONResponse(error_body("invalid_request", "Invalid request.", details=details), 422)

    @app.get("/health", tags=["health"])
    async def health(request: Request) -> dict[str, str]:
        s: Settings = request.app.state.settings
        return {
            "status": "ok",
            "version": __version__,
            "environment": s.app_env,
            "provider": s.llm_provider,
            "model": s.llm_model,
        }

    return app


app = create_app()
