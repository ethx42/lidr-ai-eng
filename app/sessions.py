"""Conversational session state: a sliding-window history, the project metadata learned so far,
and an in-memory session store.

Sessions live in process memory: they are lost on restart and not shared across workers (the
container runs one worker). That is acceptable for this phase; the `SessionStore` protocol is the
seam for a Redis or Postgres implementation.

Concurrency assumes one event loop and async endpoints: the store is touched only from that loop,
never from a thread, so it needs no lock of its own, and each session's `asyncio.Lock` serialises
its turns. The cap never evicts a session whose turn is in flight, being prepared included (its
attachments read and extracted before it takes the lock), and it takes sessions with no turns
before conversations, so a flood of creates evicts its own empty sessions first.
"""

import asyncio
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import chain
from typing import Protocol, TypeGuard, get_args

from pydantic import BaseModel

from app.schemas.estimation import RESPONSE_CONFIG, EstimationBreakdown
from app.services.providers.base import ChatMessage, ChatRole


def is_chat_role(role: str) -> TypeGuard[ChatRole]:
    return role in get_args(ChatRole)


class ConversationHistory:
    """The last `max_turns` user + assistant pairs, minus the oldest ones past `max_chars`.

    The latest pair always stays, however large: dropping it would lose the turn just answered.
    Each pair keeps its turn's raw client text (`source`, for grounding), which slides out with
    it. A pair counts the longer of its user message and its source, plus the answer, so the cap
    bounds both what the model is sent and what the session holds (neutralising can shorten a
    transcript a lot).
    """

    def __init__(self, max_turns: int = 6, max_chars: int = 60_000) -> None:
        if max_turns <= 0 or max_chars <= 0:
            raise ValueError("max_turns and max_chars must be positive")
        self._pairs: deque[tuple[str, str, str]] = deque(maxlen=max_turns)
        self._max_chars = max_chars

    def append(self, user: str, assistant: str, *, source: str = "") -> None:
        self._pairs.append((user, assistant, source))
        while len(self._pairs) > 1 and self.chars > self._max_chars:
            self._pairs.popleft()

    @property
    def turns(self) -> int:
        return len(self._pairs)

    @property
    def chars(self) -> int:
        return sum(
            max(len(user), len(source)) + len(assistant) for user, assistant, source in self._pairs
        )

    @property
    def sources(self) -> list[str]:
        return [source for _, _, source in self._pairs]

    def to_messages_list(self, system: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            *(
                message
                for user, assistant, _ in self._pairs
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


# v3 re-renders the metadata into every system prompt, outside MAX_HISTORY_CHARS.
MAX_TECHNOLOGIES = 30
MAX_TECHNOLOGY_CHARS = 80
MAX_PROJECT_NAME_CHARS = 120
MAX_SCOPE_CHARS = 1_000


def _bounded(value: str, limit: int) -> str:
    """The stripped value, or "" (no answer) when it is longer than a fact of its kind can be."""
    value = value.strip()
    return value if len(value) <= limit else ""


def merge_metadata(
    current: ProjectMetadata, breakdown: EstimationBreakdown
) -> tuple[ProjectMetadata, list[str]]:
    """Fold one answer into the known facts, in code: a blank or over-long answer never
    replaces a fact.

    Latest non-blank name and summary win, unless longer than `MAX_PROJECT_NAME_CHARS` /
    `MAX_SCOPE_CHARS`: such a value is dropped whole (a cut could flip what the scope says) and
    the known one stays. The team size is the sum of the latest team. The technologies are a
    case-insensitive union that keeps the first spelling and drops names over
    `MAX_TECHNOLOGY_CHARS`; it is capped at `MAX_TECHNOLOGIES`: once full, the known entries stay
    and new names are dropped without being reported as a change. Returns the merged metadata and
    the names of the fields that changed.
    """
    spellings: dict[str, str] = {}
    for name in (
        *current.mentioned_technologies,
        *(_bounded(t, MAX_TECHNOLOGY_CHARS) for t in breakdown.technologies),
    ):
        if name:
            spellings.setdefault(name.casefold(), name)
    merged = ProjectMetadata(
        project_name=_bounded(breakdown.project_name, MAX_PROJECT_NAME_CHARS)
        or current.project_name,
        assumed_team_size=sum(member.count for member in breakdown.team)
        or current.assumed_team_size,
        mentioned_technologies=list(spellings.values())[:MAX_TECHNOLOGIES],
        agreed_scope=_bounded(breakdown.summary, MAX_SCOPE_CHARS) or current.agreed_scope,
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
    # Turn requests in progress, counted from their checks on, so the cap cannot evict the session
    # while their attachments are read or extracted, before the turn takes the lock.
    pending: int = 0


class SessionsFull(Exception):
    """At the cap, and every session has a turn in flight."""

    code = "sessions_full"
    message = "Every session is in use. Try again shortly."


class SessionStore(Protocol):
    def create(self) -> Session:
        """Raises SessionsFull when there is no room and no session can be evicted."""
        ...

    def get(self, session_id: str) -> Session | None: ...


class InMemorySessionStore:
    """LRU-ordered: `get` refreshes a session and idle sessions expire. At the cap, `create` evicts
    an expired session, else the least recently used one with no turns, else the least recently
    used one; never one whose turn is in flight or being prepared (all of them busy:
    SessionsFull)."""

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
        now = self._clock()
        if len(self._sessions) >= self._max_sessions:
            idle = [s for s in self._sessions.values() if not (s.lock.locked() or s.pending)]
            victim = next(
                chain(
                    (s for s in idle if now - s.last_used > self._ttl_seconds),
                    (s for s in idle if s.history.turns == 0),
                    idle,
                ),
                None,
            )
            if victim is None:
                raise SessionsFull()
            del self._sessions[victim.id]
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
