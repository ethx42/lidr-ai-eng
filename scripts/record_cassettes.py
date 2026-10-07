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
from app.prompts.loader import PromptBundle, build_user_message, load_prompt
from app.schemas.estimation import EstimateRequest, EstimationBreakdown
from app.services.pricing import cost_usd
from app.services.providers.base import LLMProvider, LLMResult, TextDelta
from app.services.providers.factory import build_one
from app.services.providers.replay_provider import Cassette, Chunks, cassette_key
from evals.run_eval import FRONT_MATTER
from scripts.live_budget import ensure_budget, record_spend

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
ESTIMATE_USD = 0.01
# Recorded for a call that ends without usage: ~7k tokens in, 4096 out, rounded up.
CALL_ESTIMATE_USD = 0.004


def sample_text(sample: Path) -> str:
    """What the UI posts for this sample."""
    return FRONT_MATTER.sub("", sample.read_text(encoding="utf-8"))


def prompt_pair(sample: Path, prompt: PromptBundle) -> tuple[str, str]:
    """The service's system and user strings; the request model strips whitespace like the API."""
    request = EstimateRequest(transcription=sample_text(sample))
    return prompt.system_text, build_user_message(request.transcription, request.output_language)


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
    settings = Settings(llm_provider="openai", llm_model=MODEL, llm_fallbacks="")
    ensure_budget(ESTIMATE_USD)
    prompt = load_prompt()
    provider = build_one(settings, "openai", MODEL, settings.llm_max_retries)
    try:
        for sample in SAMPLES:
            system, user = prompt_pair(sample, prompt)
            spent = CALL_ESTIMATE_USD  # until the call reports its usage
            try:
                cassette = await record(provider, system, user, f"estimator-{prompt.version}")
                cost = cost_usd(cassette.model, cassette.usage)
                spent = CALL_ESTIMATE_USD if cost is None else cost
            finally:
                record_spend("record-cassettes", spent)
            path = save(cassette)
            usage = cassette.usage
            print(
                f"{sample.name} -> {path.relative_to(ROOT)}: {len(cassette.chunks)} chunks, "
                f"{usage.input_tokens} in ({usage.cached_input_tokens} cached) / "
                f"{usage.output_tokens} out, cost ${spent:.6f}"
            )
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
