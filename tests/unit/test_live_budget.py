import pytest

from app.schemas.estimation import Usage
from app.services.pricing import cost_usd
from scripts.live_budget import (
    PROMPT_TOKENS_BOUND,
    BudgetExceeded,
    call_bound_usd,
    ensure_budget,
    record_spend,
    total_spent,
)


def test_records_and_sums(tmp_path) -> None:
    ledger = tmp_path / "spend.jsonl"
    record_spend("smoke", 0.012, ledger=ledger)
    record_spend("eval", 0.020, ledger=ledger)
    assert total_spent(ledger) == pytest.approx(0.032)


def test_refuses_when_estimate_exceeds_remaining(tmp_path) -> None:
    ledger = tmp_path / "spend.jsonl"
    record_spend("eval", 4.99, ledger=ledger)
    with pytest.raises(BudgetExceeded):
        ensure_budget(0.05, ledger=ledger, budget=5.0)
    assert ensure_budget(0.005, ledger=ledger, budget=5.0) == pytest.approx(0.01)


def test_budget_defaults_to_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_BUDGET_USD", "0.01")
    with pytest.raises(BudgetExceeded):
        ensure_budget(0.02, ledger=tmp_path / "spend.jsonl")


def test_missing_ledger_totals_zero(tmp_path) -> None:
    assert total_spent(tmp_path / "none.jsonl") == 0.0


def test_a_call_bound_prices_the_prompt_it_is_given_as_a_cache_write() -> None:
    def worst(prompt: int) -> float | None:
        usage = Usage(input_tokens=prompt, cache_write_tokens=prompt, output_tokens=4096)
        return cost_usd("claude-haiku-4-5", usage)

    assert call_bound_usd("claude-haiku-4-5", 4096) == worst(PROMPT_TOKENS_BOUND)  # single-shot
    assert call_bound_usd("claude-haiku-4-5", 4096, prompt_tokens=200_000) == worst(200_000)
