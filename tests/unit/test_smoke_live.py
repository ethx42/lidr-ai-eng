from pathlib import Path

import pytest

from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimateRequest, EstimationBreakdown, Usage
from app.services.errors import UpstreamUnavailable
from app.services.providers.base import LLMResult, TextDelta
from app.services.providers.replay_provider import ReplayProvider, cassette_key
from scripts.record_cassettes import SAMPLES, prompt_pair, record, sample_text, save
from scripts.smoke_live import Row, failed_row, format_table, row_for
from tests.factories import breakdown, make_service, response_fixture
from tests.fakes import FakeProvider

HEADER = "| check | provider served | fallback | ttft ms | latency ms | cost usd | result |"


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
async def test_recorder_sends_the_prompt_pair_the_service_sends(sample: Path) -> None:
    fake = FakeProvider()
    service = make_service(fake)
    # The UI posts the sample file's text as is; the API strips it.
    request = EstimateRequest.model_validate({"transcription": sample_text(sample)})
    [_ async for _ in service.estimate_stream(request)]
    [call] = fake.calls
    assert prompt_pair(sample, load_prompt()) == (call["system"], call["user"])


async def test_a_recorded_cassette_is_what_replay_serves_for_that_prompt_pair(
    tmp_path: Path,
) -> None:
    system, user = prompt_pair(SAMPLES[0], load_prompt())
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
            system=system, user=user, schema=EstimationBreakdown, cache_key="k"
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
