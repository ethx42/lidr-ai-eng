import json
from pathlib import Path

import pytest

from scripts.eval_gate import main

BASELINE = {
    "prompt_version": "v4",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "score": 0.9787,
    "checks_passed": 46,
    "checks_run": 47,
    "case_pass_rate": 0.8,
    "cases": [],
}


def gate(tmp_path: Path, tolerance: str = "0.02", **report: object) -> int:
    report_path, baseline_path = tmp_path / "report.json", tmp_path / "baseline.json"
    report_path.write_text(json.dumps(BASELINE | {"prompt_version": "v1"} | report))
    baseline_path.write_text(json.dumps(BASELINE))
    return main(
        ["--report", str(report_path), "--baseline", str(baseline_path), "--tolerance", tolerance]
    )


def test_a_report_within_tolerance_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate(tmp_path, score=0.9592, checks_passed=47, checks_run=49, case_pass_rate=0.6) == 0
    out = capsys.readouterr().out
    for value in ("0.9592", "0.9787", "47/49", "46/47", "0.6", "0.8", "openai/gpt-4o-mini"):
        assert value in out
    assert "PASS" in out


def test_a_report_exactly_at_the_threshold_passes(tmp_path: Path) -> None:
    assert gate(tmp_path, score=0.9587) == 0


def test_a_report_below_tolerance_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate(tmp_path, score=0.9586) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_tighter_tolerance_fails_the_same_report(tmp_path: Path) -> None:
    assert gate(tmp_path, tolerance="0.01", score=0.9600) == 1


def test_a_report_from_another_model_fails_whatever_its_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate(tmp_path, model="claude-haiku-4-5", provider="anthropic", score=1.0) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "claude-haiku-4-5" in out
