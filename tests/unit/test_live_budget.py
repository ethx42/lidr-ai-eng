import pytest

from scripts.live_budget import BudgetExceeded, ensure_budget, record_spend, total_spent


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
