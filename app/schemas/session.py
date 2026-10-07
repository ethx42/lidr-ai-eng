"""Session-endpoint models. Not in `estimation.py`: `app.sessions` imports that module."""

from pydantic import BaseModel

from app.schemas.estimation import EstimateResponse
from app.sessions import ProjectMetadata


class SessionCreated(BaseModel):
    session_id: str


class TurnResponse(EstimateResponse):
    session_id: str
    project_metadata: ProjectMetadata
    metadata_changes: list[str]
    history_turns: int


class SessionView(BaseModel):
    session_id: str
    project_metadata: ProjectMetadata
    history_turns: int
    max_turns: int
    prompt_version: str
