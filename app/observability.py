import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.schemas.estimation import Usage

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

llm_logger = logging.getLogger("app.llm")
# Client libraries log request bodies (the transcription) at DEBUG; keep them at INFO or above.
CLIENT_LOGGERS = ("anthropic", "openai", "httpx2", "httpcore2")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [
        *(h for h in root.handlers if not isinstance(h.formatter, JsonFormatter)),
        handler,
    ]
    root.setLevel(level.upper())
    for name in CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(max(root.level, logging.INFO))


def log_llm_call(
    *,
    provider: str,
    model: str,
    prompt_version: str,
    usage: Usage | None,
    latency_ms: int,
    outcome: str,
) -> None:
    fields = {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        **(usage or Usage()).model_dump(),
        "latency_ms": latency_ms,
        "outcome": outcome,
    }
    llm_logger.info("llm_call", extra={"fields": fields, "request_id": request_id_var.get()})
