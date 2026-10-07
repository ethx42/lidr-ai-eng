"""Record the UI's sample transcripts as replay cassettes (live, budget-guarded).

`make record-cassettes` streams each sample through `OpenAIProvider` with the system and user
strings the service sends for it and writes tests/cassettes/<cassette_key>.json, the file
`ReplayProvider` looks up for that prompt pair.
"""

import asyncio
import time
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.observability import configure_logging
from app.prompts.loader import render
from app.schemas.estimation import (
    DetailLevel,
    EstimateRequest,
    EstimationBreakdown,
    OutputFormat,
    ProjectType,
)
from app.services.pricing import cost_usd
from app.services.providers.base import LLMProvider, LLMResult, TextDelta
from app.services.providers.factory import build_one
from app.services.providers.replay_provider import Cassette, Chunks, cassette_key
from evals.run_eval import FRONT_MATTER
from scripts.live_budget import call_bound_usd, ensure_budget, record_spend

ROOT = Path(__file__).resolve().parent.parent
CASSETTES = ROOT / "tests" / "cassettes"
# web/src/content/samples/ holds byte-identical copies of these, front matter stripped.
SAMPLES = tuple(
    ROOT / path
    for path in (
        "data/transcripts/course-meeting.md",
        "evals/golden/02-medium-clinic-portal.md",
        "evals/golden/03-vague-marketplace.md",
    )
)
MODEL = "gpt-4o-mini"
# The settings default, never .env's PROMPT_VERSION: the e2e stack that replays these cassettes gets
# no .env, so this is the version it serves.
DEFAULT_PROMPT_VERSION: str = Settings.model_fields["prompt_version"].default
ESTIMATE_USD = 0.01


def guard_usd(max_output_tokens: int) -> float:
    """What `ensure_budget` checks: the brief's estimate, or every call at its worst if more."""
    return max(ESTIMATE_USD, len(SAMPLES) * call_bound_usd(MODEL, max_output_tokens))


def sample_text(sample: Path) -> str:
    """What the UI posts for this sample."""
    return FRONT_MATTER.sub("", sample.read_text(encoding="utf-8"))


def sample_request(sample: Path) -> EstimateRequest:
    """The sample with the default choices; the request model strips whitespace like the API."""
    return EstimateRequest(
        transcription=sample_text(sample),
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )


def prompt_pair(sample: Path, version: str) -> tuple[str, str]:
    """The service's system and user strings for the sample's request."""
    prompt = render(sample_request(sample), version)
    return prompt.system, prompt.user


async def record(provider: LLMProvider, system: str, user: str, cache_key: str) -> Cassette:
    chunks: Chunks = []
    first: float | None = None
    async with aclosing(
        provider.stream(system=system, user=user, schema=EstimationBreakdown, cache_key=cache_key)
    ) as events:
        async for event in events:
            match event:
                case TextDelta():
                    now = time.perf_counter()
                    first = now if first is None else first
                    chunks.append((round((now - first) * 1000, 1), event.text))
                case LLMResult():
                    return Cassette(
                        key=cassette_key(system, user),
                        provider=event.provider,
                        model=event.model,
                        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                        usage=event.usage,
                        chunks=chunks,
                    )
    raise RuntimeError("the provider stream ended without a result")


def save(cassette: Cassette, directory: Path = CASSETTES) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cassette.key}.json"
    path.write_text(cassette.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


async def main() -> None:
    configure_logging("INFO")
    settings = Settings(llm_provider="openai", llm_model=MODEL, llm_fallbacks="")
    ensure_budget(guard_usd(settings.llm_max_output_tokens))
    bound = call_bound_usd(MODEL, settings.llm_max_output_tokens)
    provider = build_one(settings, "openai", MODEL, settings.llm_max_retries)
    try:
        for sample in SAMPLES:
            system, user = prompt_pair(sample, DEFAULT_PROMPT_VERSION)
            spent = bound  # until the call reports its usage
            try:
                cassette = await record(
                    provider, system, user, f"estimator-{DEFAULT_PROMPT_VERSION}"
                )
                cost = cost_usd(cassette.model, cassette.usage)
                spent = bound if cost is None else cost
            finally:
                record_spend("record-cassettes", spent)
            path = save(cassette)
            usage = cassette.usage
            print(
                f"{sample.name} -> {path.relative_to(ROOT)}: {len(cassette.chunks)} chunks, "
                f"{usage.input_tokens} in ({usage.cached_input_tokens} cached) / "
                f"{usage.output_tokens} out, cost ${spent:.6f}"
                + (" (estimated)" if cost is None else "")
            )
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
