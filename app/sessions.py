"""Conversational session state: a sliding-window history, the project metadata learned so far,
and an in-memory session store.

Sessions live in process memory: they are lost on restart and not shared across workers (the
container runs one worker). That is acceptable for this phase; the `SessionStore` protocol is the
seam for a Redis or Postgres implementation.

Concurrency assumes one event loop and async endpoints: the store is touched only from that loop,
never from a thread, so it needs no lock of its own, and each session's `asyncio.Lock` serialises
its turns. Known limitation (accepted): the cap may evict a session while a turn is in flight
(that takes `max_sessions` creates during one turn); the client still gets its answer, and its
next turn is a 404, from which the UI recovers by creating a new session.
"""

import asyncio
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeGuard, get_args

from pydantic import BaseModel

from app.schemas.estimation import RESPONSE_CONFIG, EstimationBreakdown
from app.services.providers.base import ChatMessage, ChatRole


def is_chat_role(role: str) -> TypeGuard[ChatRole]:
    return role in get_args(ChatRole)


class ConversationHistory:
    """The last `max_turns` user + assistant pairs, minus the oldest ones past `max_chars`.

    The latest pair always stays, however large: dropping it would lose the turn just answered.
    """

    def __init__(self, max_turns: int = 6, max_chars: int = 60_000) -> None:
        if max_turns <= 0 or max_chars <= 0:
            raise ValueError("max_turns and max_chars must be positive")
        self._pairs: deque[tuple[str, str]] = deque(maxlen=max_turns)
        self._max_chars = max_chars

    def append(self, user: str, assistant: str) -> None:
        self._pairs.append((user, assistant))
        while len(self._pairs) > 1 and self.chars > self._max_chars:
            self._pairs.popleft()

    @property
    def turns(self) -> int:
        return len(self._pairs)

    @property
    def chars(self) -> int:
        return sum(len(user) + len(assistant) for user, assistant in self._pairs)

    def to_messages_list(self, system: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            *(
                message
                for user, assistant in self._pairs
                for message in (
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                )
            ),
        ]

    def as_chat(self, next_user: str) -> list[ChatMessage]:
        """The window plus the new user message; the providers take the system prompt apart."""
        return [
            *(
                ChatMessage(role=message["role"], content=message["content"])
                for message in self.to_messages_list("")
                if is_chat_role(message["role"])
            ),
            ChatMessage(role="user", content=next_user),
        ]


class ProjectMetadata(BaseModel):
    model_config = RESPONSE_CONFIG

    project_name: str | None = None
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = []
    agreed_scope: str | None = None

    def is_empty(self) -> bool:
        return self == ProjectMetadata()


MAX_TECHNOLOGIES = 30


def merge_metadata(
    current: ProjectMetadata, breakdown: EstimationBreakdown
) -> tuple[ProjectMetadata, list[str]]:
    """Fold one answer into the known facts, in code: a blank answer never erases a fact.

    Latest non-blank name and summary win; the team size is the sum of the latest team; the
    technologies are a case-insensitive union that keeps the first spelling, capped. Returns the
    merged metadata and the names of the fields that changed.
    """
    spellings: dict[str, str] = {}
    for name in (*current.mentioned_technologies, *(t.strip() for t in breakdown.technologies)):
        if name:
            spellings.setdefault(name.casefold(), name)
    merged = ProjectMetadata(
        project_name=breakdown.project_name.strip() or current.project_name,
        assumed_team_size=sum(member.count for member in breakdown.team)
        or current.assumed_team_size,
        mentioned_technologies=list(spellings.values())[:MAX_TECHNOLOGIES],
        agreed_scope=breakdown.summary.strip() or current.agreed_scope,
    )
    changed = [
        field
        for field in ProjectMetadata.model_fields
        if getattr(merged, field) != getattr(current, field)
    ]
    return merged, changed


@dataclass
class Session:
    id: str
    history: ConversationHistory
    metadata: ProjectMetadata
    created_at: float
    last_used: float
    lock: asyncio.Lock


class SessionStore(Protocol):
    def create(self) -> Session: ...

    def get(self, session_id: str) -> Session | None: ...


class InMemorySessionStore:
    """LRU-ordered: `get` refreshes a session; idle sessions expire; the cap evicts the oldest."""

    def __init__(
        self,
        *,
        max_turns: int,
        max_history_chars: int,
        ttl_seconds: float,
        max_sessions: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = {
            "max_turns": max_turns,
            "max_history_chars": max_history_chars,
            "ttl_seconds": ttl_seconds,
            "max_sessions": max_sessions,
        }
        if bad := [name for name, value in settings.items() if value <= 0]:
            raise ValueError(f"{', '.join(bad)} must be positive")
        self._max_turns = max_turns
        self._max_history_chars = max_history_chars
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def create(self) -> Session:
        while len(self._sessions) >= self._max_sessions:
            self._sessions.popitem(last=False)
        now = self._clock()
        session = Session(
            id=str(uuid.uuid4()),
            history=ConversationHistory(self._max_turns, self._max_history_chars),
            metadata=ProjectMetadata(),
            created_at=now,
            last_used=now,
            lock=asyncio.Lock(),
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        now = self._clock()
        if now - session.last_used > self._ttl_seconds:
            del self._sessions[session_id]
            return None
        session.last_used = now
        self._sessions.move_to_end(session_id)
        return session
