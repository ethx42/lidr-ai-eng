"""Multi-turn estimation: each turn renders the session's prompt version with the project
metadata and the turn's attachments, sends the history window plus the new user message, and
commits the turn to the session only once the final response exists. Conversational turns never
use the exact-match cache: the same message means something else in another conversation."""

import asyncio
import contextvars
import functools
from collections.abc import AsyncGenerator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing

from app.attachments.extractor import (
    Attachment,
    AttachmentError,
    ExtractedAttachment,
    format_attachments,
)
from app.attachments.isolation import BUSY, extract_all_isolated
from app.attachments.limits import AttachmentLimits
from app.prompts.loader import RenderedPrompt, render, renders_attachments
from app.schemas.estimation import EstimateRequest, EstimateResponse
from app.schemas.session import TurnResponse
from app.schemas.stream import PartialEvent, StatusEvent
from app.services.llm_service import EstimationService
from app.services.providers.base import ChatMessage
from app.services.rendering import render_compact
from app.sessions import Session, SessionStore, merge_metadata


class SessionBusy(Exception):
    """Another turn of this session is in flight."""

    code = "session_busy"
    message = "Another turn of this session is in progress. Try again when it ends."


class SessionNotFound(Exception):
    """Unknown, expired or evicted."""

    code = "session_not_found"
    message = "Session not found or expired. Start a new session."


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
        # Extraction slots, waited for in the event loop, and one thread per slot for the child.
        self._slots = asyncio.BoundedSemaphore(limits.max_concurrent)
        self._readers = ThreadPoolExecutor(
            max_workers=limits.max_concurrent, thread_name_prefix="attachment-reader"
        )

    def start(self) -> Session:
        return self.store.create()

    def get(self, session_id: str) -> Session:
        session = self.store.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def extract(self, files: Sequence[Attachment]) -> list[ExtractedAttachment]:
        """Raises AttachmentError, "busy" when no slot frees up within the limits' timeout.

        Callers wait for one of `max_concurrent` slots here, in the event loop, so a waiting
        caller holds no thread and its busy answer keeps to the timeout. The isolated extractor
        blocks on its child process, so it runs on a thread of its own, and keeps its slot until
        the child is gone, even when this caller is cancelled first."""
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                await self._slots.acquire()
        except TimeoutError:
            raise AttachmentError(BUSY, reason="busy") from None
        run = asyncio.get_running_loop().run_in_executor(
            self._readers,
            # the request id reaches the extractor's log records, as with asyncio.to_thread
            functools.partial(
                contextvars.copy_context().run, extract_all_isolated, files, self.limits
            ),
        )
        run.add_done_callback(lambda _: self._slots.release())
        return await asyncio.shield(run)

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
    ) -> tuple[RenderedPrompt, list[ChatMessage], str, str]:
        """The prompt, the messages, this turn's client text and the grounding source.

        Quotes are checked against client text the model saw, raw (not neutralised) so verbatim
        quotes match: this turn's transcript and the attachments its version shows, then the
        client text of the turns still in the window. Never the prompt's own wording, the
        metadata or the assistant turns: those are ours or the model's.
        """
        version = self.prompt_version if prompt_version is None else prompt_version
        prompt = render(request, version, metadata=session.metadata, attachments=attachments)
        shown = attachments if renders_attachments(version) else ()
        client_text = f"{request.transcription}\n\n{format_attachments(shown)}"
        grounding_source = "\n\n".join([client_text, *session.history.sources])
        return prompt, session.history.as_chat(prompt.user), client_text, grounding_source

    def _commit(
        self, session: Session, prompt: RenderedPrompt, client_text: str, response: EstimateResponse
    ) -> TurnResponse:
        compact = render_compact(response.breakdown)
        metadata, changes = merge_metadata(session.metadata, response.breakdown)
        turn = TurnResponse(
            **dict(response),
            session_id=session.id,
            project_metadata=metadata,
            metadata_changes=changes,
            history_turns=0,  # set below, once the turn is in
        )
        # Plain assignments from here: the turn lands whole or not at all.
        session.history.append(prompt.user, compact, source=client_text)
        session.metadata = metadata
        turn.history_turns = session.history.turns
        return turn

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
            prompt, messages, client_text, source = self._prepare(
                session, request, attachments, prompt_version
            )
            response = await self.estimation.run(prompt, messages, request, source, use_cache=False)
            return self._commit(session, prompt, client_text, response)

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
            prompt, messages, client_text, source = self._prepare(
                session, request, attachments, prompt_version
            )
            async with aclosing(
                self.estimation.stream_run(prompt, messages, request, source, use_cache=False)
            ) as items:
                async for item in items:
                    yield (
                        self._commit(session, prompt, client_text, item)
                        if isinstance(item, EstimateResponse)
                        else item
                    )
