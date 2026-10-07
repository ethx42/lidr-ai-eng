"""USD cost of an LLM call from its token usage."""

from dataclasses import dataclass

from app.schemas.estimation import Usage

PRICES_CHECKED = "2026-10-06"


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    cached_input: float
    cache_write: float
    output: float


# Standard tier, checked on PRICES_CHECKED at https://developers.openai.com/api/docs/pricing and
# https://platform.claude.com/docs/en/about-claude/pricing. OpenAI bills no separate cache write
# (input rate); Anthropic's write rate is the 5-minute TTL. Matched by longest model-id prefix.
PRICES: dict[str, Price] = {
    "gpt-4o-mini": Price(0.15, 0.075, 0.15, 0.60),
    "claude-haiku-4-5": Price(1.00, 0.10, 1.25, 5.00),
}


def cost_usd(model: str, usage: Usage) -> float | None:
    matches = [prefix for prefix in PRICES if model.startswith(prefix)]
    if not matches:
        return None
    price = PRICES[max(matches, key=len)]
    # Both providers report `input_tokens` as the total, cache reads and writes included.
    cached, written = usage.cached_input_tokens, usage.cache_write_tokens
    uncached = max(usage.input_tokens - cached - written, 0)
    total = (
        uncached * price.input
        + cached * price.cached_input
        + written * price.cache_write
        + usage.output_tokens * price.output
    )
    return round(total / 1_000_000, 6)
