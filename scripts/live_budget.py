"""Spend guard for live LLM calls: JSON-lines ledger plus a hard budget (LIVE_BUDGET_USD)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.estimation import Usage
from app.services.pricing import cost_usd

LEDGER = Path(__file__).resolve().parent.parent / "docs" / "catch-up" / "spend.jsonl"
# Above any request here: system prompt, schema and sample measured 6.4k-6.6k input tokens.
PROMPT_TOKENS_BOUND = 8_000


class BudgetExceeded(RuntimeError):
    pass


def total_spent(ledger: Path = LEDGER) -> float:
    if not ledger.exists():
        return 0.0
    return sum(
        float(json.loads(line)["cost_usd"]) for line in ledger.read_text().splitlines() if line
    )


def record_spend(command: str, cost_usd: float, *, ledger: Path = LEDGER) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "command": command}
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**entry, "cost_usd": cost_usd}) + "\n")


def ensure_budget(
    estimated_usd: float, *, ledger: Path = LEDGER, budget: float | None = None
) -> float:
    limit = budget if budget is not None else float(os.environ.get("LIVE_BUDGET_USD", "5"))
    remaining = limit - total_spent(ledger)
    if estimated_usd > remaining:
        raise BudgetExceeded(f"estimate ${estimated_usd:.4f} exceeds remaining ${remaining:.4f}")
    return remaining


def call_bound_usd(model: str, max_output_tokens: int) -> float:
    """One call's worst case: the whole prompt billed as a cache write, then every output token."""
    usage = Usage(
        input_tokens=PROMPT_TOKENS_BOUND,
        cache_write_tokens=PROMPT_TOKENS_BOUND,
        output_tokens=max_output_tokens,
    )
    cost = cost_usd(model, usage)
    if cost is None:
        raise ValueError(f"no price for {model}: cannot bound live spend")
    return cost
