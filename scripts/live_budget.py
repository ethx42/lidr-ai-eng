"""Spend guard for live LLM calls: JSON-lines ledger plus a hard budget (LIVE_BUDGET_USD)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "docs" / "catch-up" / "spend.jsonl"


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
