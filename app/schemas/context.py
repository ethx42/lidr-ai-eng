"""What `GET /api/v1/context` shows the UI inspector: the prompt and references the model sees."""

from pydantic import BaseModel

from app.schemas.estimation import RESPONSE_CONFIG, EstimationBreakdown


class ReferenceView(BaseModel):
    model_config = RESPONSE_CONFIG

    size: str
    meeting_summary: str
    estimation: EstimationBreakdown


class ContextResponse(BaseModel):
    model_config = RESPONSE_CONFIG

    prompt_version: str
    system_prompt: str
    references: list[ReferenceView]
    chain: list[str]  # "provider:model", primary first
    max_transcription_chars: int
