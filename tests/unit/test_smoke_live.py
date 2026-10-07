from pathlib import Path

import pytest

from app.config import Settings
from app.prompts.loader import DEFAULT_VERSION
from app.schemas.estimation import EstimationBreakdown, Usage
from app.services.errors import UpstreamUnavailable
from app.services.providers.base import ChatMessage, LLMResult, TextDelta
from app.services.providers.fallback import FallbackProvider
from app.services.providers.openai_provider import OpenAIProvider
from app.services.providers.replay_provider import Cassette, ReplayProvider, cassette_key
from scripts import record_cassettes, smoke_live
from scripts.live_budget import PROMPT_TOKENS_BOUND, call_bound_usd
from scripts.record_cassettes import (
    CASSETTES,
    SAMPLES,
    prompt_pair,
    record,
    sample_text,
    save,
)
from scripts.smoke_live import Row, failed_row, format_table, row_for
from tests.factories import breakdown, make_service, response_fixture, typed_request
from tests.fakes import FakeProvider

HEADER = "| check | provider served | fallback | ttft ms | latency ms | cost usd | result |"


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
async def test_recorder_sends_the_prompt_pair_the_service_sends(sample: Path) -> None:
    fake = FakeProvider()
    service = make_service(fake)
    # The UI posts the sample file's text as is; the API strips it.
    request = typed_request(sample_text(sample))
    [_ async for _ in service.estimate_stream(request)]
    [call] = fake.calls
    system, user = prompt_pair(sample, service.prompt_version)
    assert (call["system"], call["messages"]) == (system, [ChatMessage("user", user)])


async def test_a_recorded_cassette_is_what_replay_serves_for_that_prompt_pair(
    tmp_path: Path,
) -> None:
    system, user = prompt_pair(SAMPLES[0], DEFAULT_VERSION)
    cassette = await record(FakeProvider(model="gpt-4o-mini"), system, user, "estimator-test")
    path = save(cassette, tmp_path)

    assert path == tmp_path / f"{cassette_key(system, user)}.json"
    assert (cassette.provider, cassette.model) == ("openai", "gpt-4o-mini")
    assert cassette.chunks[0][0] == 0  # timed from the first delta
    replay = ReplayProvider(
        cassette_dir=tmp_path, fallback=[breakdown(project_name="Other")], delay_scale=0
    )
    events = [
        e
        async for e in replay.stream(
            system=system,
            messages=[ChatMessage("user", user)],
            schema=EstimationBreakdown,
            cache_key="k",
        )
    ]
    assert [e.text for e in events if isinstance(e, TextDelta)] == [t for _, t in cassette.chunks]
    final = events[-1]
    assert isinstance(final, LLMResult)
    assert (
        final.usage
        == cassette.usage
        == Usage(
            input_tokens=1200, output_tokens=800, cached_input_tokens=1024, cache_write_tokens=176
        )
    )


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_every_sample_has_a_current_cassette(sample: Path) -> None:
    # The e2e stack replays with no .env, so it serves the settings default version.
    key = cassette_key(*prompt_pair(sample, Settings.model_fields["prompt_version"].default))
    path = CASSETTES / f"{key}.json"
    # A prompt or sample change moves the key; replay would then quietly synthesise a stream.
    assert path.is_file(), f"stale cassettes: no {path.name}; run `make record-cassettes`"
    assert Cassette.model_validate_json(path.read_bytes()).key == key


async def test_the_recorder_propagates_a_failed_stream() -> None:
    with pytest.raises(UpstreamUnavailable):
        await record(FakeProvider(error=UpstreamUnavailable()), "S", "U", "k")


def test_table_prints_one_row_per_check_under_the_documented_header() -> None:
    rows = [
        Row("openai stream", "openai:gpt-4o-mini", False, 412, 5180, 0.002345, "pass"),
        Row("forced fallback", None, None, None, None, None, "FAIL: upstream_unavailable"),
    ]
    assert format_table(rows).splitlines() == [
        HEADER,
        "|---|---|---|---|---|---|---|",
        "| openai stream | openai:gpt-4o-mini | no | 412 | 5180 | 0.002345 | pass |",
        "| forced fallback | - | - | - | - | - | FAIL: upstream_unavailable |",
    ]


def test_a_row_passes_when_the_expected_provider_streamed_it() -> None:
    fixture = response_fixture()
    metrics = fixture.metrics.model_copy(update={"ttft_ms": 310, "cost_usd": 0.0021})
    response = fixture.model_copy(update={"metrics": metrics})
    row = row_for("openai stream", response, provider="openai", fallback=False)
    assert row == Row("openai stream", "openai:fake-model", False, 310, 42, 0.0021, "pass")
    assert row.passed


def test_a_row_fails_naming_every_unmet_expectation() -> None:
    response = response_fixture()  # served by openai, no fallback, never streamed (no ttft)
    row = row_for("forced fallback", response, provider="anthropic", fallback=True)
    assert row.result == "FAIL: served by openai; fallback_used=False; no ttft"
    assert not row.passed


def test_a_failed_check_reports_the_error_code_and_cause() -> None:
    row = failed_row("anthropic stream", UpstreamUnavailable(reason="overloaded_error"))
    assert row == Row(
        "anthropic stream",
        None,
        None,
        None,
        None,
        None,
        "FAIL: upstream_unavailable (overloaded_error)",
    )
    assert not row.passed


def test_a_call_bound_bills_the_whole_prompt_as_a_cache_write_and_every_output_token() -> None:
    prompt = PROMPT_TOKENS_BOUND
    assert call_bound_usd("gpt-4o-mini", 4096) == pytest.approx(
        (prompt * 0.15 + 4096 * 0.60) / 1e6, abs=1e-6
    )
    assert call_bound_usd("claude-haiku-4-5", 4096) == pytest.approx(
        (prompt * 1.25 + 4096 * 5.00) / 1e6, abs=1e-6
    )
    assert call_bound_usd("claude-haiku-4-5", 1024) < call_bound_usd("claude-haiku-4-5", 4096)


def test_the_recorder_guard_covers_every_sample_failing_at_its_worst_case() -> None:
    worst = len(SAMPLES) * call_bound_usd("gpt-4o-mini", 4096)
    assert worst > record_cassettes.ESTIMATE_USD
    assert record_cassettes.guard_usd(4096) == pytest.approx(worst)
    assert record_cassettes.guard_usd(16) == record_cassettes.ESTIMATE_USD


def test_the_smoke_guard_covers_every_check_failing_at_its_worst_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env: the settings come from the variables below
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "4096")
    checks = smoke_live.default_checks()
    openai, haiku = call_bound_usd("gpt-4o-mini", 4096), call_bound_usd("claude-haiku-4-5", 4096)
    # The dead primary of the forced fallback never bills; its Anthropic fallback can.
    assert [check.bound_usd for check in checks] == [openai, haiku, haiku]
    assert smoke_live.guard_usd(checks) == pytest.approx(openai + 2 * haiku)
    assert smoke_live.guard_usd(checks) > smoke_live.ESTIMATE_USD

    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "16")
    assert smoke_live.guard_usd(smoke_live.default_checks()) == smoke_live.ESTIMATE_USD


async def test_the_dead_primary_never_carries_the_real_openai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    fallback_check = smoke_live.default_checks()[-1]
    router = fallback_check.build(fallback_check.settings)
    assert isinstance(router, FallbackProvider)
    dead = router.chain[0]
    assert isinstance(dead, OpenAIProvider)
    assert str(dead.client.base_url).startswith(smoke_live.DEAD_URL)
    assert dead.client.api_key != "test-openai-key"
    await router.aclose()
