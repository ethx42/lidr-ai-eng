import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimationBreakdown
from app.services.errors import InvalidModelOutput
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMResult
from evals.run_eval import GOLDEN_DIR, GoldenCase, load_golden_cases, main, run_cases
from tests.factories import TRANSCRIPT, breakdown, task
from tests.fakes import FakeProvider

ROOT = Path(__file__).resolve().parents[2]


def test_golden_set_loads() -> None:
    cases = load_golden_cases(GOLDEN_DIR)
    assert len(cases) >= 3
    assert all(case.transcript.strip() for case in cases)
    names = [case.name for case in cases]
    assert "01-course-meeting" in names
    assert [case.name for case in cases if case.vague] == ["03-vague-marketplace"]


def test_course_transcript_is_in_golden_set() -> None:
    course = (ROOT / "data/transcripts/course-meeting.md").read_text()
    [case] = [c for c in load_golden_cases(GOLDEN_DIR) if c.name == "01-course-meeting"]
    assert case.transcript == course


T = TypeVar("T", bound=BaseModel)

FULL = breakdown(
    tasks=[
        task("T1", basis=["R1"]),
        task("T2", basis=["R2"], phase="qa"),
        task("T3", basis=["A1"], phase="devops"),
        task("T4", basis=["R1"], phase="project_management"),
    ]
)
MISSING_DEVOPS = breakdown(tasks=[t for t in FULL.tasks if t.phase != "devops"])


class ScriptedProvider(FakeProvider):
    def __init__(self, outcomes: list[EstimationBreakdown | Exception]) -> None:
        super().__init__()
        self.outcomes = outcomes

    async def generate(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.result = outcome
        return await super().generate(system=system, user=user, schema=schema)


async def run(outcomes: list[EstimationBreakdown | Exception], names: list[str]) -> dict[str, Any]:
    provider = ScriptedProvider(outcomes)
    service = EstimationService(
        provider=provider, prompt=load_prompt(), weekly_capacity_hours=30, hourly_rate=None
    )
    cases = [GoldenCase(name, TRANSCRIPT) for name in names]
    return await run_cases(service, cases, provider="openai", model="fake-model")


async def test_all_checks_pass() -> None:
    report = await run([FULL, FULL, FULL], ["a", "b", "c"])
    assert report["score"] == 1.0
    assert report["case_pass_rate"] == 1.0
    assert report["checks_run"] == 24


async def test_score_granularity() -> None:
    report = await run([FULL, MISSING_DEVOPS, FULL], ["a", "b", "c"])
    assert report["case_pass_rate"] == round(2 / 3, 4)
    assert report["case_pass_rate"] < report["score"] < 1
    assert report["score"] == round(23 / 24, 4)
    failing = report["cases"][1]
    assert failing["checks"]["covers_devops"] is False


async def test_fabricated_requirement_fails_grounding() -> None:
    fabricated = breakdown(
        requirements=[
            {"id": "R1", "statement": "s", "evidence": "a booking app"},
            {"id": "R2", "statement": "s", "evidence": "never said this"},
        ],
        tasks=FULL.tasks,
    )
    [case] = (await run([fabricated], ["a"]))["cases"]
    assert case["grounding_passed"] is False
    assert case["grounding"]["ungrounded_requirement_ids"] == ["R2"]


async def test_vague_case_checks() -> None:
    confident = FULL.model_copy(update={"confidence": "high", "open_questions": []})
    [case] = (await run([confident], ["03-vague-x"]))["cases"]
    assert case["checks"]["has_open_questions"] is False
    assert case["checks"]["confidence_below_high"] is False


async def test_provider_failure_counts_all_checks_failed() -> None:
    report = await run([InvalidModelOutput(), FULL], ["a", "b"])
    assert report["cases"][0]["error"] == "invalid_model_output"
    assert report["checks_run"] == 16
    assert report["score"] == 0.5


async def test_explicit_report_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "nested" / "report.json"
    settings = Settings(_env_file=None, openai_api_key="test-key")
    fake = FakeProvider(result=FULL)
    path = await main(["--report", str(target)], settings=settings, provider_factory=lambda _: fake)
    assert path == target
    report = json.loads(target.read_text())
    assert 0 <= report["score"] <= 1
    assert report["prompt_version"] == "v1"
    assert len(report["cases"]) == len(load_golden_cases(GOLDEN_DIR))
    assert fake.closed
    assert "score=" in capsys.readouterr().out


async def test_default_report_name_includes_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.run_eval as run_eval

    monkeypatch.setattr(run_eval, "REPORTS_DIR", tmp_path)
    settings = Settings(_env_file=None, openai_api_key="test-key")
    path = await main([], settings=settings, provider_factory=lambda _: FakeProvider(result=FULL))
    assert path.parent == tmp_path
    assert path.name.startswith("v1-")
