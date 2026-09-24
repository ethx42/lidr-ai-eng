"""Live prompt evaluation over the golden set (`make eval`). Never part of `make check`."""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.prompts.loader import load_prompt
from app.schemas.estimation import EnrichedBreakdown, EstimateRequest, EstimateResponse
from app.services.errors import LLMError
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.services.providers.factory import build_provider

ROOT = Path(__file__).resolve().parent
GOLDEN_DIR = ROOT / "golden"
REPORTS_DIR = ROOT / "reports"
LIKELY_HOURS_BOUNDS = (4, 80)
NON_BUILD_PHASES = ("qa", "devops", "project_management")

STOPWORDS = {
    "english": {
        "the", "and", "to", "of", "for", "with", "is", "are", "be", "will", "on", "this",
        "that", "we", "it", "as", "by", "from", "or", "their", "each", "should", "which",
    },
    "spanish": {
        "el", "la", "los", "las", "de", "del", "que", "y", "para", "con", "por", "un", "una",
        "es", "son", "se", "al", "su", "sus", "como", "más", "lo", "cada", "debe", "según",
    },
}  # fmt: skip
LANGUAGE_NAMES = {
    "english": "english",
    "inglés": "english",
    "spanish": "spanish",
    "español": "spanish",
}
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class GoldenCase:
    name: str
    transcript: str
    output_language: str | None = None

    @property
    def vague(self) -> bool:
        return "vague" in self.name


def parse_case(path: Path) -> GoldenCase:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        return GoldenCase(path.stem, text)
    meta = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return GoldenCase(
        path.stem, text[match.end() :], meta.get("output_language", "").strip() or None
    )


def load_golden_cases(directory: Path = GOLDEN_DIR) -> list[GoldenCase]:
    return [parse_case(p) for p in sorted(directory.glob("*.md"))]


def detect_language(text: str) -> str | None:
    """English/Spanish by stopword frequency; None when there is too little signal."""
    words = re.findall(r"[a-záéíóúñü]+", text.casefold())
    counts = {lang: sum(w in stop for w in words) for lang, stop in STOPWORDS.items()}
    (top, top_count), (_, other_count) = sorted(counts.items(), key=lambda kv: -kv[1])
    return top if top_count >= 5 and top_count > 1.5 * other_count else None


def expected_language(case: GoldenCase) -> str | None:
    if case.output_language:
        return LANGUAGE_NAMES.get(case.output_language.casefold())
    return detect_language(case.transcript)


def narrative_text(b: EnrichedBreakdown) -> str:
    parts = [b.summary, b.confidence_rationale, *b.open_questions]
    parts += [r.statement for r in b.requirements]
    parts += [f"{a.statement} {a.impact_if_wrong}" for a in b.assumptions]
    parts += [f"{t.name} {t.rationale}" for t in b.tasks]
    parts += [f"{r.description} {r.mitigation}" for r in b.risks]
    return "\n".join(parts)


def check_response(case: GoldenCase, response: EstimateResponse | None) -> dict[str, bool]:
    if response is None:
        names = ["schema_valid", "three_point_order", "hours_within_bounds"]
        names += [f"covers_{p}" for p in NON_BUILD_PHASES]
        names += ["requirements_grounded", "tasks_have_valid_basis", "narrative_language"]
        names += ["has_open_questions", "confidence_below_high"] if case.vague else []
        return dict.fromkeys(names, False)

    b, g = response.breakdown, response.grounding
    low, high = LIKELY_HOURS_BOUNDS
    checks = {
        "schema_valid": True,
        "three_point_order": all(
            t.optimistic_hours <= t.likely_hours <= t.pessimistic_hours for t in b.tasks
        ),
        "hours_within_bounds": all(low <= t.likely_hours <= high for t in b.tasks),
        **{f"covers_{p}": any(t.phase == p for t in b.tasks) for p in NON_BUILD_PHASES},
        "requirements_grounded": not g.ungrounded_requirement_ids,
        "tasks_have_valid_basis": not g.tasks_without_valid_basis,
        "narrative_language": (expected := expected_language(case)) is not None
        and detect_language(narrative_text(b)) == expected,
    }
    if case.vague:
        checks["has_open_questions"] = bool(b.open_questions)
        checks["confidence_below_high"] = b.confidence != "high"
    return checks


async def evaluate_case(service: EstimationService, case: GoldenCase) -> dict[str, Any]:
    start = time.perf_counter()
    response: EstimateResponse | None = None
    error: str | None = None
    try:
        response = await service.estimate(
            EstimateRequest(transcription=case.transcript, output_language=case.output_language)
        )
    except LLMError as exc:
        error = exc.code
    checks = check_response(case, response)
    return {
        "name": case.name,
        "passed": all(checks.values()),
        "grounding_passed": checks["requirements_grounded"] and checks["tasks_have_valid_basis"],
        "checks": checks,
        "error": error,
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "narrative_language": {
            "expected": expected_language(case),
            "detected": detect_language(narrative_text(response.breakdown)) if response else None,
        },
        "grounding": response.grounding.model_dump() if response else None,
        "usage": response.usage.model_dump() if response else None,
        "confidence": response.breakdown.confidence if response else None,
        "open_questions": len(response.breakdown.open_questions) if response else None,
        "tasks": len(response.breakdown.tasks) if response else None,
        "expected_hours": response.breakdown.totals.expected_hours if response else None,
    }


async def run_cases(
    service: EstimationService, cases: Sequence[GoldenCase], *, provider: str, model: str
) -> dict[str, Any]:
    results = [await evaluate_case(service, case) for case in cases]
    checks = [ok for r in results for ok in r["checks"].values()]
    return {
        "prompt_version": service.prompt.version,
        "provider": provider,
        "model": model,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "score": round(sum(checks) / len(checks), 4) if checks else 0.0,
        "checks_passed": sum(checks),
        "checks_run": len(checks),
        "case_pass_rate": round(sum(r["passed"] for r in results) / len(results), 4)
        if results
        else 0.0,
        "cases": results,
    }


def write_report(report: dict[str, Any], path: Path | None) -> Path:
    if path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = REPORTS_DIR / f"{report['prompt_version']}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def summary_table(report: dict[str, Any]) -> str:
    rows = [f"{'case':<28} {'pass':<5} {'checks':<7} {'grounding':<9} {'hours':>7} {'ms':>7}"]
    for r in report["cases"]:
        checks = r["checks"]
        grounding = r["grounding"]["score"] if r["grounding"] else "-"
        rows.append(
            f"{r['name']:<28} {'yes' if r['passed'] else 'NO':<5} "
            f"{sum(checks.values())}/{len(checks):<5} {grounding!s:<9} "
            f"{r['expected_hours'] or '-'!s:>7} {r['latency_ms']:>7}"
            + (f"  error={r['error']}" if r["error"] else "")
        )
    rows.append(
        f"score={report['score']} ({report['checks_passed']}/{report['checks_run']} checks)  "
        f"case_pass_rate={report['case_pass_rate']}  "
        f"{report['provider']}/{report['model']} prompt {report['prompt_version']}"
    )
    return "\n".join(rows)


async def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], LLMProvider] = build_provider,
) -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write the JSON report to exactly this path")
    args = parser.parse_args(argv)

    resolved = settings or Settings()
    provider = provider_factory(resolved)
    service = EstimationService(
        provider=provider,
        prompt=load_prompt(),
        weekly_capacity_hours=resolved.weekly_capacity_hours,
        hourly_rate=resolved.blended_hourly_rate,
    )
    try:
        report = await run_cases(
            service, load_golden_cases(), provider=provider.name, model=provider.model
        )
    finally:
        await provider.aclose()
    path = write_report(report, args.report)
    print(summary_table(report))
    print(f"report: {path}")
    return path


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
