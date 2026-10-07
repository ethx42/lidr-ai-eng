"""Payloads of the SSE events sent by `POST /api/v1/estimate/stream` (the `result` event carries
an `EstimateResponse`)."""

from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.estimation import RESPONSE_CONFIG


class StatusEvent(BaseModel):
    model_config = RESPONSE_CONFIG

    phase: Literal["calling_llm", "fallback", "validating", "cache_hit"]
    provider: str | None = None
    model: str | None = None


class PartialEvent(BaseModel):
    seq: int
    breakdown: dict[str, Any]  # partial EstimationBreakdown: any JSON value, possibly incomplete


class ErrorEvent(BaseModel):
    code: str
    message: str
    retryable: bool
    request_id: str
