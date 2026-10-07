"""Live smoke test (`make smoke-live`, budget-guarded): a streamed estimate through OpenAI, one
through Anthropic, and a forced fallback, each through the service (no response cache) and printed
as one table row. Exits 1 if any check fails."""

import asyncio
import sys
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import astuple, dataclass

from openai import AsyncOpenAI

from app.config import Provider, Settings
from app.observability import configure_logging
from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimateRequest, EstimateResponse
from app.services.cache import NullCache, cache_scope
from app.services.errors import LLMError
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_one, build_provider
from app.services.providers.fallback import Cooldown, FallbackProvider
from app.services.providers.openai_provider import OpenAIProvider
from app.services.providers.profiles import get_profile
from scripts.live_budget import call_bound_usd, ensure_budget, record_spend
from scripts.record_cassettes import SAMPLES, sample_text

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5"
DEAD_URL = "http://127.0.0.1:9"  # discard port: nothing listens, so the primary never answers
DEAD_KEY = "sk-unused"  # never send a real key to a port that anything local could open
ESTIMATE_USD = 0.05
COLUMNS = ("check", "provider served", "fallback", "ttft ms", "latency ms", "cost usd", "result")


@dataclass(frozen=True)
class Row:
    check: str
    provider: str | None  # provider:model that served the result
    fallback: bool | None
    ttft_ms: int | None
    latency_ms: int | None
    cost_usd: float | None
    result: str  # "pass" or "FAIL: <why>"

    @property
    def passed(self) -> bool:
        return self.result == "pass"


@dataclass(frozen=True)
class Check:
    name: str
    serves: Provider
    model: str  # the model that bills for this check
    fallback: bool
    settings: Settings
    build: Callable[[Settings], LLMProvider]

    @property
    def bound_usd(self) -> float:
        """Recorded when the check reports no cost."""
        return call_bound_usd(self.model, self.settings.llm_max_output_tokens)


def _cell(value: str | bool | float | None) -> str:
    match value:
        case None:
            return "-"
        case bool():
            return "yes" if value else "no"
        case float():
            return f"{value:.6f}"
        case _:
            return str(value)


def format_table(rows: Sequence[Row]) -> str:
    def line(cells: Sequence[str]) -> str:
        return f"| {' | '.join(cells)} |"

    body = [line([_cell(value) for value in astuple(row)]) for row in rows]
    return "\n".join([line(COLUMNS), "|" + "---|" * len(COLUMNS), *body])


def row_for(check: str, response: EstimateResponse, *, provider: Provider, fallback: bool) -> Row:
    metrics = response.metrics
    expectations = {
        f"served by {response.provider}": response.provider == provider,
        f"fallback_used={metrics.fallback_used}": metrics.fallback_used == fallback,
        "no ttft": metrics.ttft_ms is not None,
    }
    problems = [problem for problem, met in expectations.items() if not met]
    return Row(
        check,
        f"{response.provider}:{response.model}",
        metrics.fallback_used,
        metrics.ttft_ms,
        metrics.latency_ms,
        metrics.cost_usd,
        f"FAIL: {'; '.join(problems)}" if problems else "pass",
    )


def failed_row(check: str, exc: LLMError) -> Row:
    cause = f" ({exc.cause})" if exc.cause else ""
    return Row(check, None, None, None, None, None, f"FAIL: {exc.code}{cause}")


def dead_primary(settings: Settings) -> LLMProvider:
    """OpenAI at a closed port (refused at once, or cut by the 2 s timeout), then Anthropic."""
    client = AsyncOpenAI(api_key=DEAD_KEY, base_url=DEAD_URL, timeout=2, max_retries=0)
    primary = OpenAIProvider(
        client=client,
        model=OPENAI_MODEL,
        profile=get_profile(OPENAI_MODEL, "openai", settings.llm_reasoning_effort),
        temperature=settings.llm_temperature,
        reasoning_effort=settings.llm_reasoning_effort,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    fallback = build_one(settings, "anthropic", ANTHROPIC_MODEL, settings.llm_max_retries)
    cooldown = Cooldown(
        failures=settings.llm_cooldown_failures, seconds=settings.llm_cooldown_seconds
    )
    return FallbackProvider([primary, fallback], cooldown)


async def run(check: Check) -> Row:
    settings = check.settings
    provider = check.build(settings)
    service = EstimationService(
        provider=provider,
        prompt=load_prompt(),
        weekly_capacity_hours=settings.weekly_capacity_hours,
        hourly_rate=settings.blended_hourly_rate,
        cache=NullCache(),  # every check must reach a provider
        cache_scope=cache_scope(settings),
    )
    request = EstimateRequest(transcription=sample_text(SAMPLES[0]))
    try:
        async with aclosing(service.estimate_stream(request)) as items:
            [response] = [item async for item in items if isinstance(item, EstimateResponse)]
    except LLMError as exc:
        return failed_row(check.name, exc)
    finally:
        await provider.aclose()
    return row_for(check.name, response, provider=check.serves, fallback=check.fallback)


def default_checks() -> list[Check]:
    """Builds the settings, so a missing key fails before anything is spent."""
    return [
        Check(
            "openai stream",
            serves="openai",
            model=OPENAI_MODEL,
            fallback=False,
            settings=Settings(llm_provider="openai", llm_model=OPENAI_MODEL, llm_fallbacks=""),
            build=build_provider,
        ),
        Check(
            "anthropic stream",
            serves="anthropic",
            model=ANTHROPIC_MODEL,
            fallback=False,
            settings=Settings(
                llm_provider="anthropic", llm_model=ANTHROPIC_MODEL, llm_fallbacks=""
            ),
            build=build_provider,
        ),
        Check(
            "forced fallback",
            serves="anthropic",
            model=ANTHROPIC_MODEL,  # the dead primary never bills
            fallback=True,
            settings=Settings(
                llm_provider="openai",
                llm_model=OPENAI_MODEL,
                llm_fallbacks=f"anthropic:{ANTHROPIC_MODEL}",
            ),
            build=dead_primary,
        ),
    ]


def guard_usd(checks: Sequence[Check]) -> float:
    """What `ensure_budget` checks: the brief's estimate, or every check at its worst if more."""
    return max(ESTIMATE_USD, sum(check.bound_usd for check in checks))


async def main() -> int:
    configure_logging("INFO")
    checks = default_checks()
    ensure_budget(guard_usd(checks))
    rows: list[Row] = []
    for check in checks:
        spent = check.bound_usd  # until the check reports its cost
        try:
            row = await run(check)
            spent = check.bound_usd if row.cost_usd is None else row.cost_usd
        finally:
            record_spend("smoke-live", spent)
        rows.append(row)
    print(format_table(rows))
    return 0 if all(row.passed for row in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
