import pytest

from app.schemas.estimation import Usage
from app.services.pricing import cost_usd


def test_openai_cached_tokens_billed_at_cached_rate() -> None:
    usage = Usage(
        input_tokens=10_000, output_tokens=1_000, cached_input_tokens=8_000, cache_write_tokens=0
    )
    # (2000*0.15 + 8000*0.075 + 1000*0.60) / 1e6
    assert cost_usd("gpt-4o-mini", usage) == pytest.approx(0.0015)


def test_anthropic_dated_snapshot_matches_by_prefix() -> None:
    usage = Usage(
        input_tokens=9_000, output_tokens=1_000, cached_input_tokens=6_000, cache_write_tokens=2_000
    )
    # uncached 1000*1.00 + read 6000*0.10 + write 2000*1.25 + out 1000*5.00
    assert cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(0.0091)


def test_unknown_model_has_no_cost() -> None:
    assert cost_usd("mystery-model", Usage(input_tokens=1, output_tokens=1)) is None
