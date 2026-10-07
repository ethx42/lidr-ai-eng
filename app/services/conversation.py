"""Multi-turn estimation: each turn renders the session's prompt version with the project
metadata and the turn's attachments, sends the history window plus the new user message, and
commits the turn to the session only once the final response exists. Conversational turns never
use the exact-match cache: the same message means something else in another conversation."""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

from app.attachments.extractor import Attachment, ExtractedAttachment, format_attachments
from app.attachments.isolation import extract_all_isolated
from app.attachments.limits import AttachmentLimits
from app.prompts.loader import RenderedPrompt, render
from app.schemas.estimation import EstimateRequest, EstimateResponse
from app.schemas.session import TurnResponse
from app.schemas.stream import PartialEvent, StatusEvent
from app.services.llm_service import EstimationService
from app.services.providers.base import ChatMessage
from app.services.rendering import render_compact
from app.sessions import Session, SessionStore, merge_metadata


class SessionBusy(Exception):
    """Another turn of this session is in flight."""


class SessionNotFound(Exception):
    """Unknown, expired or evicted."""


class ConversationService:
    def __init__(
        self,
        *,
        estimation: EstimationService,
        store: SessionStore,
        limits: AttachmentLimits,
        prompt_version: str = "v3",
    ) -> None:
        self.estimation = estimation
        self.store = store
        self.limits = limits
        self.prompt_version = prompt_version

    def start(self) -> Session:
        return self.store.create()

    def get(self, session_id: str) -> Session:
        session = self.store.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def extract(self, files: Sequence[Attachment]) -> list[ExtractedAttachment]:
        """Raises AttachmentError. The isolated extractor blocks while it waits on its child
        process, so it runs in a worker thread."""
        return await asyncio.to_thread(extract_all_isolated, files, self.limits)

    def _idle(self, session_id: str) -> Session:
        """The session, unless a turn holds it. Callers take its lock before their first await,
        so no other turn can slip in between this check and the lock."""
        session = self.get(session_id)
        if session.lock.locked():
            raise SessionBusy(session_id)
        return session

    def _prepare(
        self,
        session: Session,
        request: EstimateRequest,
        attachments: Sequence[ExtractedAttachment],
        prompt_version: str | None,
    ) -> tuple[RenderedPrompt, list[ChatMessage], str]:
        prompt = render(
            request,
            self.prompt_version if prompt_version is None else prompt_version,
            metadata=session.metadata,
            attachments=attachments,
        )
        messages = session.history.as_chat(prompt.user)
        # Quotable text the model saw: this turn's transcript and attachments (un-neutralised, so
        # verbatim quotes match), then the user turns still in the window. Never the system prompt,
        # the metadata or the assistant turns: those are model output.
        grounding_source = "\n\n".join(
            [
                request.transcription,
                format_attachments(attachments),
                *(m.content for m in messages[:-1] if m.role == "user"),
            ]
        )
        return prompt, messages, grounding_source

    def _commit(
        self, session: Session, prompt: RenderedPrompt, response: EstimateResponse
    ) -> TurnResponse:
        session.history.append(prompt.user, render_compact(response.breakdown))
        session.metadata, changes = merge_metadata(session.metadata, response.breakdown)
        return TurnResponse(
            **dict(response),
            session_id=session.id,
            project_metadata=session.metadata,
            metadata_changes=changes,
            history_turns=session.history.turns,
        )

    async def turn(
        self,
        session_id: str,
        request: EstimateRequest,
        attachments: Sequence[ExtractedAttachment],
        *,
        prompt_version: str | None = None,
    ) -> TurnResponse:
        session = self._idle(session_id)
        async with session.lock:
            prompt, messages, source = self._prepare(session, request, attachments, prompt_version)
            response = await self.estimation.run(prompt, messages, request, source, use_cache=False)
            return self._commit(session, prompt, response)

    async def turn_stream(
        self,
        session_id: str,
        request: EstimateRequest,
        attachments: Sequence[ExtractedAttachment],
        *,
        prompt_version: str | None = None,
    ) -> AsyncGenerator[StatusEvent | PartialEvent | TurnResponse]:
        """`turn`, streamed. Closed or cancelled before the final response, it leaves the session
        as it was; either way the lock is released when the generator ends."""
        session = self._idle(session_id)
        async with session.lock:
            prompt, messages, source = self._prepare(session, request, attachments, prompt_version)
            async with aclosing(
                self.estimation.stream_run(prompt, messages, request, source, use_cache=False)
            ) as items:
                async for item in items:
                    yield (
                        self._commit(session, prompt, item)
                        if isinstance(item, EstimateResponse)
                        else item
                    )
