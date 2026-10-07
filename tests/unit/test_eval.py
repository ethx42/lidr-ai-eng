import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimationBreakdown
from app.services.cache import NullCache
from app.services.errors import InvalidModelOutput
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMResult
from evals.run_eval import (
    GOLDEN_DIR,
    GoldenCase,
    detect_language,
    expected_language,
    load_golden_cases,
    main,
    run_cases,
)
from scripts.live_budget import BudgetExceeded, call_bound_usd
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

    async def generate(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> LLMResult[T]:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.result = outcome
        return await super().generate(system=system, user=user, schema=schema, cache_key=cache_key)


async def run(outcomes: list[EstimationBreakdown | Exception], names: list[str]) -> dict[str, Any]:
    provider = ScriptedProvider(outcomes)
    service = EstimationService(
        provider=provider,
        prompt=load_prompt(),
        weekly_capacity_hours=30,
        hourly_rate=None,
        cache=NullCache(),
        cache_scope="",
    )
    cases = [GoldenCase(name, TRANSCRIPT) for name in names]
    return await run_cases(service, cases, provider="openai", model="fake-model")


async def test_all_checks_pass() -> None:
    report = await run([FULL, FULL, FULL], ["a", "b", "c"])
    assert report["score"] == 1.0
    assert report["case_pass_rate"] == 1.0
    assert report["checks_run"] == 27
    assert {"cached_input_tokens", "cache_write_tokens"} <= report["cases"][0]["usage"].keys()


async def test_score_granularity() -> None:
    report = await run([FULL, MISSING_DEVOPS, FULL], ["a", "b", "c"])
    assert report["case_pass_rate"] == round(2 / 3, 4)
    assert report["case_pass_rate"] < report["score"] < 1
    assert report["score"] == round(26 / 27, 4)
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
    assert report["checks_run"] == 18
    assert report["score"] == 0.5


async def test_explicit_report_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "nested" / "report.json"
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    fake = FakeProvider(result=FULL)
    path = await main(["--report", str(target)], settings=settings, provider_factory=lambda _: fake)
    assert path == target
    report = json.loads(target.read_text())
    assert 0 <= report["score"] <= 1
    assert report["prompt_version"] == "v4"
    assert len(report["cases"]) == len(load_golden_cases(GOLDEN_DIR))
    assert fake.closed
    assert "score=" in capsys.readouterr().out


async def test_default_report_name_includes_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals import run_eval

    monkeypatch.setattr(run_eval, "REPORTS_DIR", tmp_path)
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    path = await main([], settings=settings, provider_factory=lambda _: FakeProvider(result=FULL))
    assert path.parent == tmp_path
    assert path.name.startswith("v4-")


def test_detect_language() -> None:
    assert (
        detect_language("We will build the booking flow and the payments for each studio.")
        == "english"
    )
    assert (
        detect_language("Vamos a construir el flujo de reservas y los pagos para cada estudio.")
        == "spanish"
    )
    assert detect_language("Stripe, Holded, SAP") is None


def test_front_matter_declares_output_language() -> None:
    cases = {c.name: c for c in load_golden_cases(GOLDEN_DIR)}
    explicit = cases["05-explicit-language"]
    assert explicit.output_language == "Spanish"
    assert not explicit.transcript.startswith("---")
    assert cases["01-course-meeting"].output_language is None
    assert expected_language(explicit) == "spanish"
    assert expected_language(cases["01-course-meeting"]) == "english"
    assert expected_language(cases["04-injection-es"]) == "spanish"


SPANISH_NARRATIVE = FULL.model_copy(
    update={
        "summary": "Aplicación de reservas para el estudio con pagos y panel para el personal.",
        "confidence_rationale": "El alcance es claro, pero faltan detalles de las integraciones.",
        "open_questions": ["¿Qué sistema de calendario se usa hoy en el estudio?"],
        "tasks": [
            t.model_copy(
                update={
                    "name": "Tarea del proyecto",
                    "rationale": "Necesaria para el flujo de reservas.",
                }
            )
            for t in FULL.tasks
        ],
    }
)


async def test_unknown_expected_language_fails_check() -> None:
    service = EstimationService(
        provider=ScriptedProvider([FULL]),
        prompt=load_prompt(),
        weekly_capacity_hours=30,
        hourly_rate=None,
        cache=NullCache(),
        cache_scope="",
    )
    case = GoldenCase("x", "Stripe. SAP. OK.")
    report = await run_cases(service, [case], provider="openai", model="fake-model")
    assert report["cases"][0]["narrative_language"]["expected"] is None
    assert report["cases"][0]["checks"]["narrative_language"] is False


def test_every_golden_case_has_an_expected_language() -> None:
    expected = {c.name: expected_language(c) for c in load_golden_cases(GOLDEN_DIR)}
    assert expected == {
        "01-course-meeting": "english",
        "02-medium-clinic-portal": "english",
        "03-vague-marketplace": "english",
        "04-injection-es": "spanish",
        "05-explicit-language": "spanish",
    }


async def test_wrong_narrative_language_fails_check() -> None:
    [case] = (await run([SPANISH_NARRATIVE], ["a"]))["cases"]
    assert case["checks"]["narrative_language"] is False
    assert case["narrative_language"] == {"expected": "english", "detected": "spanish"}


async def test_matching_narrative_language_passes_check() -> None:
    [case] = (await run([FULL], ["a"]))["cases"]
    assert case["checks"]["narrative_language"] is True


async def test_explicit_output_language_is_sent_and_checked() -> None:
    provider = ScriptedProvider([SPANISH_NARRATIVE])
    service = EstimationService(
        provider=provider,
        prompt=load_prompt(),
        weekly_capacity_hours=30,
        hourly_rate=None,
        cache=NullCache(),
        cache_scope="",
    )
    case = GoldenCase("x", TRANSCRIPT, output_language="Spanish")
    report = await run_cases(service, [case], provider="openai", model="fake-model")
    assert "<output_language>Spanish</output_language>" in provider.calls[0]["user"]
    assert report["cases"][0]["checks"]["narrative_language"] is True


async def test_ledger_guards_and_records_eval_spend(tmp_path: Path) -> None:
    ledger = tmp_path / "spend.jsonl"
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    await main(
        ["--report", str(tmp_path / "r.json")],
        settings=settings,
        provider_factory=lambda _: FakeProvider(result=FULL),
        ledger=ledger,
    )
    assert json.loads(ledger.read_text().splitlines()[-1])["command"] == "eval"


async def test_eval_spend_is_the_summed_call_cost(tmp_path: Path) -> None:
    ledger = tmp_path / "spend.jsonl"
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    path = await main(
        ["--report", str(tmp_path / "r.json")],
        settings=settings,
        provider_factory=lambda _: FakeProvider(result=FULL, model="gpt-4o-mini"),
        ledger=ledger,
    )
    costs = [case["cost_usd"] for case in json.loads(path.read_text())["cases"]]
    assert all(cost > 0 for cost in costs)
    recorded = json.loads(ledger.read_text().splitlines()[-1])["cost_usd"]
    assert recorded == pytest.approx(sum(costs))


async def test_eval_runs_the_primary_provider_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "LLM_FALLBACKS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)  # no .env here
    seen: list[Settings] = []

    def factory(settings: Settings) -> FakeProvider:
        seen.append(settings)
        return FakeProvider(result=FULL)

    await main(["--report", str(tmp_path / "r.json")], provider_factory=factory)
    assert [s.chain for s in seen] == [[("openai", "gpt-4o-mini")]]


def ledger_entries(ledger: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []


async def test_the_eval_guard_covers_every_case_at_its_worst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Five Haiku cases at their worst (~$0.15) do not fit in $0.12, though the old fixed $0.10 did.
    monkeypatch.setenv("LIVE_BUDGET_USD", "0.12")
    called: list[Settings] = []

    def factory(resolved: Settings) -> FakeProvider:
        called.append(resolved)
        return FakeProvider(result=FULL)

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5",
        llm_fallbacks="",
        llm_max_output_tokens=4096,
    )
    worst = len(load_golden_cases()) * call_bound_usd("claude-haiku-4-5", 4096)
    assert worst > 0.12
    with pytest.raises(BudgetExceeded):
        await main(
            ["--report", str(tmp_path / "r.json")],
            settings=settings,
            provider_factory=factory,
            ledger=tmp_path / "spend.jsonl",
        )
    assert called == []


async def test_eval_refuses_a_model_it_cannot_price(tmp_path: Path) -> None:
    ledger = tmp_path / "spend.jsonl"
    settings = Settings(
        _env_file=None, openai_api_key="test-key", llm_model="gpt-4.1", llm_fallbacks=""
    )
    with pytest.raises(ValueError, match="cannot bound live spend"):
        await main(
            ["--report", str(tmp_path / "r.json")],
            settings=settings,
            provider_factory=lambda _: FakeProvider(result=FULL, model="gpt-4.1"),
            ledger=ledger,
        )
    assert ledger_entries(ledger) == []


@pytest.mark.parametrize(
    "error,raised",
    [(InvalidModelOutput(), None), (RuntimeError("cut off"), RuntimeError)],
    ids=["failed-cases", "run-raises-midway"],
)
async def test_eval_spend_without_a_reported_cost_is_recorded_at_its_bound(
    error: Exception, raised: type[Exception] | None, tmp_path: Path
) -> None:
    ledger = tmp_path / "spend.jsonl"
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    run_eval = main(
        ["--report", str(tmp_path / "r.json")],
        settings=settings,
        provider_factory=lambda _: FakeProvider(error=error, model="gpt-4o-mini"),
        ledger=ledger,
    )
    if raised:
        with pytest.raises(raised):
            await run_eval
    else:
        await run_eval
    [entry] = ledger_entries(ledger)
    bound = call_bound_usd("gpt-4o-mini", settings.llm_max_output_tokens)
    assert entry["cost_usd"] == pytest.approx(len(load_golden_cases()) * bound)
