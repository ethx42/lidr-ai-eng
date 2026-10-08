import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.conversation import ConversationService
from app.services.errors import UpstreamUnavailable
from app.services.pricing import cost_usd
from app.services.providers.base import ChatMessage
from scripts import smoke_live_session
from scripts.live_budget import BudgetExceeded, call_bound_usd, record_spend, total_spent
from tests.factories import breakdown
from tests.fakes import FakeProvider

# What FakeProvider reports for every call.
TURN_USD = cost_usd(
    "gpt-4o-mini",
    Usage(input_tokens=1200, output_tokens=800, cached_input_tokens=1024, cache_write_tokens=176),
)
# A line of tests/fixtures/attachments/spec.pdf.
PDF_LINE = "ATTACHMENT-MARKER: offline payments via Redsys"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)  # no .env: the settings come from the variables below
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.delenv("LIVE_BUDGET_USD", raising=False)
    return smoke_live_session.pinned_settings()


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    return tmp_path / "spend.jsonl"


def fake_with(*answers: EstimationBreakdown) -> FakeProvider:
    fake = FakeProvider(model="gpt-4o-mini")
    for answer in answers:
        fake.queue(answer)
    return fake


async def run(settings: Settings, fake: FakeProvider, ledger: Path) -> int:
    return await smoke_live_session.main(
        settings=settings, provider_factory=lambda _: fake, ledger=ledger
    )


def ledger_commands(ledger: Path) -> list[str]:
    return [json.loads(line)["command"] for line in ledger.read_text().splitlines()]


def kept(*technologies: Sequence[str]) -> list[EstimationBreakdown]:
    return [breakdown(project_name="Lumen Checkout", technologies=list(t)) for t in technologies]


async def test_three_turns_pass_and_record_their_summed_cost(
    settings: Settings, ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = fake_with(*kept(["Stripe"], ["Redsys"], []))
    assert await run(settings, fake, ledger) == 0

    assert len(fake.calls) == 3
    second: list[ChatMessage] = fake.calls[1]["messages"]
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert "--- attachment: spec.pdf ---" in second[-1].content
    assert "--- attachment:" not in fake.calls[2]["messages"][-1].content
    assert total_spent(ledger) == pytest.approx(3 * TURN_USD)
    out = capsys.readouterr().out
    assert out.count("metadata:") == 3
    assert out.splitlines()[-1].endswith(": pass")
    # Prints what the session learned, never what the client sent.
    for turn in smoke_live_session.TURNS:
        assert turn.transcript not in out
    assert "ATTACHMENT-MARKER" not in out


async def test_the_scope_is_printed_as_its_length_only(
    settings: Settings, ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The live turn 2 summary repeated the PDF's marker line: scope text can quote attachments.
    summary = f"Checkout that must support {PDF_LINE}."
    answer = breakdown(project_name="Lumen Checkout", technologies=["Redsys"], summary=summary)
    assert await run(settings, fake_with(answer, answer, answer), ledger) == 0

    out = capsys.readouterr().out
    assert PDF_LINE not in out and "offline payments" not in out
    assert out.count(f'"agreed_scope": "{len(summary)} chars"') == 3
    assert '"project_name": "Lumen Checkout"' in out and '"Redsys"' in out


@pytest.mark.parametrize(
    "answers",
    [
        [breakdown(project_name=name, technologies=["Redsys"]) for name in ("A", "B", "A")],
        [breakdown(project_name=" ", technologies=["Redsys"]) for _ in range(3)],
    ],
    ids=["renamed", "never named"],
)
async def test_fails_unless_the_project_name_is_kept_on_every_turn(
    settings: Settings,
    ledger: Path,
    capsys: pytest.CaptureFixture[str],
    answers: list[EstimationBreakdown],
) -> None:
    assert await run(settings, fake_with(*answers), ledger) == 1
    assert "FAIL: project_name not kept" in capsys.readouterr().out.splitlines()[-1]
    assert total_spent(ledger) == pytest.approx(3 * TURN_USD)


@pytest.mark.parametrize(
    "technologies",
    [(["Stripe"], ["Stripe"], ["Redsys"]), (["Stripe"], [], [])],
    ids=["only after turn 3", "never"],
)
async def test_fails_when_redsys_is_missing_after_the_turn_with_the_pdf(
    settings: Settings,
    ledger: Path,
    capsys: pytest.CaptureFixture[str],
    technologies: tuple[list[str], ...],
) -> None:
    assert await run(settings, fake_with(*kept(*technologies)), ledger) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert "FAIL: Redsys missing from the technologies after turn 2" in last


async def test_redsys_matches_whatever_the_model_calls_it(settings: Settings, ledger: Path) -> None:
    fake = fake_with(*kept([], ["REDSYS payment gateway"], []))
    assert await run(settings, fake, ledger) == 0


async def test_a_failed_turn_is_charged_its_bound_and_ends_the_run(
    settings: Settings, ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = fake_with()

    def answer(messages: Sequence[ChatMessage]) -> EstimationBreakdown:
        if len(fake.calls) == 2:
            raise UpstreamUnavailable(reason="overloaded_error")
        return breakdown(project_name="Lumen Checkout", technologies=["Redsys"])

    fake.respond_with = answer
    assert await run(settings, fake, ledger) == 1

    assert len(fake.calls) == 2
    bound = smoke_live_session.turn_bound_usd(settings)
    assert total_spent(ledger) == pytest.approx(TURN_USD + bound)
    last = capsys.readouterr().out.splitlines()[-1]
    assert "FAIL: turn 2: upstream_unavailable (overloaded_error)" in last
    assert fake.closed


async def test_a_rejected_attachment_is_not_charged_and_ends_with_a_summary(
    settings: Settings,
    ledger: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renamed_exe = tmp_path / "spec.pdf"
    renamed_exe.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00")
    first, second, third = smoke_live_session.TURNS
    turns = (first, replace(second, attachments=(renamed_exe,)), third)
    monkeypatch.setattr(smoke_live_session, "TURNS", turns)
    fake = fake_with(*kept(["Stripe"]))
    assert await run(settings, fake, ledger) == 1

    assert len(fake.calls) == 1  # turn 2 never reached the provider
    assert total_spent(ledger) == pytest.approx(TURN_USD)
    last = capsys.readouterr().out.splitlines()[-1]
    assert "FAIL: turn 2: invalid_attachment (spec.pdf: unsupported file type" in last
    assert fake.closed


async def test_the_provider_is_closed_and_spend_recorded_when_the_session_cannot_start(
    settings: Settings, ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_session(self: ConversationService) -> None:
        raise RuntimeError("no session")

    monkeypatch.setattr(ConversationService, "start", no_session)
    fake = fake_with()
    with pytest.raises(RuntimeError, match="no session"):
        await run(settings, fake, ledger)
    assert fake.closed and fake.calls == []
    assert ledger_commands(ledger) == ["smoke-live-session"] and total_spent(ledger) == 0


async def test_refuses_before_any_call_when_the_budget_cannot_cover_it(
    settings: Settings, ledger: Path
) -> None:
    record_spend("earlier", 4.99, ledger=ledger)
    built: list[Settings] = []

    def factory(s: Settings) -> FakeProvider:
        built.append(s)
        return FakeProvider()

    with pytest.raises(BudgetExceeded):
        await smoke_live_session.main(settings=settings, provider_factory=factory, ledger=ledger)
    assert built == []
    assert total_spent(ledger) == pytest.approx(4.99)


def test_the_chain_is_pinned_whatever_the_env_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    assert smoke_live_session.pinned_settings().chain == [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-haiku-4-5"),
    ]


def test_the_guard_covers_every_turn_at_its_worst_case(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    haiku = call_bound_usd("claude-haiku-4-5", 4096)
    # The dearer model of the chain may serve any turn.
    assert smoke_live_session.turn_bound_usd(settings) == pytest.approx(haiku)
    assert smoke_live_session.guard_usd(settings) == pytest.approx(3 * haiku)
    assert smoke_live_session.guard_usd(settings) > smoke_live_session.ESTIMATE_USD

    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "16")
    small = smoke_live_session.pinned_settings()
    assert smoke_live_session.guard_usd(small) == smoke_live_session.ESTIMATE_USD
