"""Eval gate: a prompt version must score within `--tolerance` of the baseline, on the baseline's
model. Prints both reports side by side; exits 1 when the gate fails.

uv run python -m scripts.eval_gate --report <new.json> --baseline evals/baseline.json
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel


class Report(BaseModel):
    """The summary fields of an `evals/run_eval.py` report."""

    prompt_version: str
    provider: str
    model: str
    score: float
    checks_passed: int
    checks_run: int
    case_pass_rate: float


def load(path: Path) -> Report:
    return Report.model_validate_json(path.read_bytes())


def side_by_side(report: Report, baseline: Report) -> str:
    rows = [
        ("", "report", "baseline"),
        ("prompt_version", report.prompt_version, baseline.prompt_version),
        ("score", str(report.score), str(baseline.score)),
        (
            "checks",
            f"{report.checks_passed}/{report.checks_run}",
            f"{baseline.checks_passed}/{baseline.checks_run}",
        ),
        ("case_pass_rate", str(report.case_pass_rate), str(baseline.case_pass_rate)),
        (
            "provider/model",
            f"{report.provider}/{report.model}",
            f"{baseline.provider}/{baseline.model}",
        ),
    ]
    return "\n".join(f"{name:<16} {new:<22} {old}" for name, new, old in rows)


def failures(report: Report, baseline: Report, tolerance: float) -> list[str]:
    # Scores carry four decimals; rounding keeps float noise from moving the threshold.
    threshold = round(baseline.score - tolerance, 6)
    found: list[str] = []
    if report.model != baseline.model:
        found.append(f"model {report.model} differs from the baseline's {baseline.model}")
    if report.score < threshold:
        found.append(f"score {report.score} is below {threshold} (baseline - {tolerance})")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.02)
    args = parser.parse_args(argv)

    report, baseline = load(args.report), load(args.baseline)
    print(side_by_side(report, baseline))
    found = failures(report, baseline, args.tolerance)
    for failure in found:
        print(f"FAIL: {failure}")
    if not found:
        print(f"PASS: score {report.score} >= baseline {baseline.score} - {args.tolerance}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
