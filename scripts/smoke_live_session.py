"""Live three-turn session check (`make smoke-live-session`, budget-guarded): one in-process
session against the real provider chain, the second turn with a PDF attached. Prints what the
session learned after each turn, never the transcripts or the attachment text. Exits 1 if the
project name is not kept across turns or Redsys (named only in the PDF) is missing from the
technologies after turn 2."""

import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path

from app.attachments.extractor import Attachment
from app.config import Settings
from app.observability import configure_logging
from app.schemas.estimation import DetailLevel, EstimateRequest, OutputFormat, ProjectType
from app.schemas.session import TurnResponse
from app.services.cache import NullCache, cache_scope
from app.services.conversation import ConversationService
from app.services.errors import LLMError
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_provider
from app.sessions import InMemorySessionStore
from scripts.live_budget import LEDGER, call_bound_usd, ensure_budget, record_spend

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5"
ESTIMATE_USD = 0.05
PDF = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "attachments" / "spec.pdf"
ATTACHMENT_ONLY_TECHNOLOGY = "Redsys"


@dataclass(frozen=True)
class Turn:
    transcript: str
    attachments: tuple[Path, ...] = ()


TURNS = (
    Turn(
        "PM: Thanks for joining. Let's call the project Lumen Checkout.\n"
        "Client: We sell homeware online and our checkout loses customers. We want a new web "
        "checkout: cart review, shipping address, card payments with Stripe and an order "
        "confirmation email.\n"
        "PM: Who uses it?\n"
        "Client: Our customers, on desktop and mobile browsers.\n"
        "PM: Any deadline?\n"
        "Client: Before the November sales."
    ),
    Turn(
        "Client: I attached the payments specification from our bank. The checkout must also "
        "take payments through the gateway it describes, and refunds must follow it.\n"
        "PM: Understood, we will read it before the next session.",
        (PDF,),
    ),
    Turn(
        "Client: One more thing: our support team wants an admin page to issue refunds and "
        "resend confirmation emails. Everything else stays as we agreed.\n"
        "PM: Noted."
    ),
)


def pinned_settings() -> Settings:
    """The chain is pinned whatever `.env` says; a missing key fails before anything is spent."""
    return Settings(
        llm_provider="openai",
        llm_model=OPENAI_MODEL,
        llm_fallbacks=f"anthropic:{ANTHROPIC_MODEL}",
    )


def turn_bound_usd(settings: Settings) -> float:
    """A turn's worst case: the dearest model of the chain serves it. Recorded for a turn that
    started but reported no cost."""
    return max(call_bound_usd(model, settings.llm_max_output_tokens) for _, model in settings.chain)


def guard_usd(settings: Settings) -> float:
    """What `ensure_budget` checks: the brief's estimate, or every turn at its worst if more."""
    return max(ESTIMATE_USD, len(TURNS) * turn_bound_usd(settings))


def conversation_for(settings: Settings, provider: LLMProvider) -> ConversationService:
    estimation = EstimationService(
        provider=provider,
        prompt_version=settings.prompt_version,
        weekly_capacity_hours=settings.weekly_capacity_hours,
        hourly_rate=settings.blended_hourly_rate,
        cache=NullCache(),  # session turns bypass the cache anyway
        cache_scope=cache_scope(settings),
    )
    store = InMemorySessionStore(
        max_turns=settings.max_turns,
        max_history_chars=settings.max_history_chars,
        ttl_seconds=settings.session_ttl_seconds,
        max_sessions=settings.max_sessions,
    )
    return ConversationService(
        estimation=estimation, store=store, limits=settings.attachment_limits
    )


async def take_turn(conversation: ConversationService, session_id: str, turn: Turn) -> TurnResponse:
    files = [Attachment(path.name, path.read_bytes()) for path in turn.attachments]
    extracted = await conversation.extract(files) if files else []
    request = EstimateRequest(
        transcription=turn.transcript,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )
    async with aclosing(conversation.turn_stream(session_id, request, extracted)) as items:
        [response] = [item async for item in items if isinstance(item, TurnResponse)]
    return response


def format_turn(number: int, turn: Turn, response: TurnResponse) -> str:
    usage, metrics, grounding = response.usage, response.metrics, response.grounding
    attached = f" + {', '.join(p.name for p in turn.attachments)}" if turn.attachments else ""
    cost = "-" if metrics.cost_usd is None else f"{metrics.cost_usd:.6f}"
    cells = [
        f"turn {number}{attached}: {response.provider}:{response.model}",
        f"fallback {'yes' if metrics.fallback_used else 'no'}",
        f"tokens in {usage.input_tokens} (cached {usage.cached_input_tokens})",
        f"out {usage.output_tokens}",
        f"cost {cost}",
        f"grounded {grounding.requirements_grounded}/{grounding.requirements_total}",
        f"history {response.history_turns}",
        f"changes: {', '.join(response.metadata_changes) or '-'}",
    ]
    metadata = json.dumps(response.project_metadata.model_dump())
    return f"{' | '.join(cells)}\n  metadata: {metadata}"


def problems(responses: Sequence[TurnResponse]) -> list[str]:
    names = [response.project_metadata.project_name for response in responses]
    found = []
    if None in names or len(set(names)) > 1:
        found.append(f"project_name not kept ({' -> '.join(map(str, names))})")
    after_pdf = responses[1].project_metadata.mentioned_technologies
    if not any(ATTACHMENT_ONLY_TECHNOLOGY.casefold() in t.casefold() for t in after_pdf):
        found.append(f"{ATTACHMENT_ONLY_TECHNOLOGY} missing from the technologies after turn 2")
    return found


def summary(responses: Sequence[TurnResponse], spent: float, failures: Sequence[str]) -> str:
    served = ", ".join(f"{r.provider}:{r.model}" for r in responses) or "-"
    result = f"FAIL: {'; '.join(failures)}" if failures else "pass"
    return f"smoke-live-session: {len(responses)} turns ({served}), total {spent:.6f} usd: {result}"


async def main(
    *,
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], LLMProvider] = build_provider,
    ledger: Path = LEDGER,
) -> int:
    resolved = settings or pinned_settings()
    ensure_budget(guard_usd(resolved), ledger=ledger)
    bound = turn_bound_usd(resolved)
    provider = provider_factory(resolved)
    conversation = conversation_for(resolved, provider)
    session_id = conversation.start().id
    costs: list[float] = []
    responses: list[TurnResponse] = []
    try:
        for number, turn in enumerate(TURNS, start=1):
            costs.append(bound)  # until the turn reports its cost
            response = await take_turn(conversation, session_id, turn)
            costs[-1] = bound if response.metrics.cost_usd is None else response.metrics.cost_usd
            responses.append(response)
            print(format_turn(number, turn, response))
    except LLMError as exc:
        cause = f" ({exc.cause})" if exc.cause else ""
        failures = [f"turn {len(costs)}: {exc.code}{cause}"]
    else:
        failures = problems(responses)
    finally:
        record_spend("smoke-live-session", sum(costs), ledger=ledger)
        await provider.aclose()
    print(summary(responses, sum(costs), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    configure_logging("INFO")
    sys.exit(asyncio.run(main()))
