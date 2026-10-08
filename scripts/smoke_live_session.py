"""Live three-turn session check (`make smoke-live-session`, budget-guarded): one in-process
session against the real provider chain, the second turn with a PDF attached. Prints what the
session learned after each turn (the scope as its length only), never the transcripts or the
attachment text. Exits 1 if a turn fails, the project name is not kept across turns, Redsys
(named only in the PDF) is missing from the technologies after turn 2, or turn 3, which only adds
an admin page, drops scope: fewer requirements than turn 2, or no requirement or task that still
mentions Stripe (named only in turn 1)."""

import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path

from app.attachments.extractor import Attachment, AttachmentError, ExtractedAttachment
from app.config import Settings
from app.main import build_services
from app.observability import configure_logging
from app.schemas.estimation import DetailLevel, EstimateRequest, OutputFormat, ProjectType
from app.schemas.session import TurnResponse
from app.services.cache import NullCache
from app.services.conversation import ConversationService
from app.services.errors import LLMError
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_provider
from scripts.live_budget import LEDGER, call_bound_usd, ensure_budget, record_spend

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5"
ESTIMATE_USD = 0.05
PDF = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "attachments" / "spec.pdf"
ATTACHMENT_ONLY_TECHNOLOGY = "Redsys"
TURN_ONE_ONLY_FACT = "Stripe"


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


async def extract(conversation: ConversationService, turn: Turn) -> list[ExtractedAttachment]:
    """Raises AttachmentError, before any provider call."""
    files = [Attachment(path.name, path.read_bytes()) for path in turn.attachments]
    return await conversation.extract(files) if files else []


async def take_turn(
    conversation: ConversationService,
    session_id: str,
    turn: Turn,
    attachments: Sequence[ExtractedAttachment],
) -> TurnResponse:
    request = EstimateRequest(
        transcription=turn.transcript,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )
    async with aclosing(conversation.turn_stream(session_id, request, attachments)) as items:
        [response] = [item async for item in items if isinstance(item, TurnResponse)]
    return response


def mentions(response: TurnResponse, fact: str) -> bool:
    b = response.breakdown
    texts = [
        *(f"{r.statement} {r.evidence}" for r in b.requirements),
        *(f"{t.name} {t.rationale}" for t in b.tasks),
    ]
    return any(fact.casefold() in text.casefold() for text in texts)


def format_turn(number: int, turn: Turn, response: TurnResponse) -> str:
    usage, metrics, grounding = response.usage, response.metrics, response.grounding
    kept = mentions(response, TURN_ONE_ONLY_FACT)  # where turn 1's scope was kept, or lost
    attached = f" + {', '.join(p.name for p in turn.attachments)}" if turn.attachments else ""
    cost = "-" if metrics.cost_usd is None else f"{metrics.cost_usd:.6f}"
    cells = [
        f"turn {number}{attached}: {response.provider}:{response.model}",
        f"fallback {'yes' if metrics.fallback_used else 'no'}",
        f"tokens in {usage.input_tokens} (cached {usage.cached_input_tokens})",
        f"out {usage.output_tokens}",
        f"cost {cost}",
        f"grounded {grounding.requirements_grounded}/{grounding.requirements_total}",
        f"mentions {TURN_ONE_ONLY_FACT} {'yes' if kept else 'no'}",
        f"history {response.history_turns}",
        f"changes: {', '.join(response.metadata_changes) or '-'}",
    ]
    facts = response.project_metadata.model_dump()
    scope = response.project_metadata.agreed_scope
    # The scope is the model's summary, and it can quote an attachment: its length only.
    facts["agreed_scope"] = None if scope is None else f"{len(scope)} chars"
    return f"{' | '.join(cells)}\n  metadata: {json.dumps(facts)}"


def problems(responses: Sequence[TurnResponse]) -> list[str]:
    names = [response.project_metadata.project_name for response in responses]
    found = []
    if None in names or len(set(names)) > 1:
        found.append(f"project_name not kept ({' -> '.join(map(str, names))})")
    after_pdf = responses[1].project_metadata.mentioned_technologies
    if not any(ATTACHMENT_ONLY_TECHNOLOGY.casefold() in t.casefold() for t in after_pdf):
        found.append(f"{ATTACHMENT_ONLY_TECHNOLOGY} missing from the technologies after turn 2")
    # Turn 3 only adds an admin page: its answer must still be the whole project.
    second, third = (r.grounding.requirements_total for r in responses[1:3])
    if third < second:
        found.append(f"turn 3 dropped scope (requirements {second} -> {third})")
    if not mentions(responses[2], TURN_ONE_ONLY_FACT):
        found.append(
            f"turn 3 dropped turn 1's scope (no requirement or task mentions {TURN_ONE_ONLY_FACT})"
        )
    return found


def failed_turn(number: int, exc: LLMError | AttachmentError) -> str:
    if isinstance(exc, AttachmentError):  # its message names the file and the reason only
        code = "attachments_busy" if exc.reason == "busy" else "invalid_attachment"
        return f"turn {number}: {code} ({exc})"
    cause = f" ({exc.cause})" if exc.cause else ""
    return f"turn {number}: {exc.code}{cause}"


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
    costs: list[float] = []
    responses: list[TurnResponse] = []
    try:
        _, conversation = build_services(resolved, provider, NullCache())  # turns bypass it anyway
        session_id = conversation.start().id
        for number, turn in enumerate(TURNS, start=1):
            attachments = await extract(conversation, turn)  # no provider call yet: no charge
            costs.append(bound)  # until the turn reports its cost
            response = await take_turn(conversation, session_id, turn, attachments)
            costs[-1] = bound if response.metrics.cost_usd is None else response.metrics.cost_usd
            responses.append(response)
            print(format_turn(number, turn, response))
    except (LLMError, AttachmentError) as exc:
        failures = [failed_turn(len(responses) + 1, exc)]
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
