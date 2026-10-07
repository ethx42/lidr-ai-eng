import asyncio
import json
from pathlib import Path

import pytest

from app.schemas.estimation import EstimationBreakdown
from app.services.errors import InvalidModelOutput
from app.services.pricing import cost_usd
from app.services.providers.base import ChatMessage, LLMResult, TextDelta
from app.services.providers.replay_provider import ReplayProvider, cassette_key
from tests.factories import breakdown

MESSAGES = [ChatMessage("user", "U")]


def write_cassette(directory: Path, key: str, chunks: list[list[object]]) -> None:
    (directory / f"{key}.json").write_text(
        json.dumps(
            {
                "key": key,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "recorded_at": "x",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cached_input_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "chunks": chunks,
            }
        )
    )


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record)
    return recorded


async def test_replays_cassette_text_and_timing(tmp_path: Path) -> None:
    breakdown_json = breakdown().model_dump_json()
    key = cassette_key("S", "U")
    (tmp_path / f"{key}.json").write_text(
        json.dumps(
            {
                "key": key,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "recorded_at": "x",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cached_input_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "chunks": [[0, breakdown_json[:20]], [10, breakdown_json[20:]]],
            }
        )
    )
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=0)
    events = [
        e
        async for e in p.stream(
            system="S", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
        )
    ]
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert "".join(d.text for d in deltas) == breakdown_json
    assert deltas[-1].snapshot == breakdown_json
    final = events[-1]
    assert (
        isinstance(final, LLMResult)
        and final.provider == "replay"
        and final.usage.input_tokens == 10
    )


async def test_synthesises_a_stream_without_cassette(tmp_path: Path) -> None:
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=0)
    events = [
        e
        async for e in p.stream(
            system="S",
            messages=[ChatMessage("user", "other")],
            schema=EstimationBreakdown,
            cache_key="k",
        )
    ]
    assert len([e for e in events if isinstance(e, TextDelta)]) > 3
    assert isinstance(events[-1], LLMResult)


async def test_generate_returns_the_same_parsed_result(tmp_path: Path) -> None:
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=0)
    result = await p.generate(
        system="S", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
    )
    assert result.parsed == breakdown()


def test_cassette_key_is_sha256_of_the_prompt_pair() -> None:
    # `printf 'S\0U' | shasum -a 256`
    assert cassette_key("S", "U") == (
        "73c2db13edc9b680044aa1d33e0cf0543e53976ffc017d39c8486c97a18b5e0d"
    )


async def test_cassette_sleeps_follow_recorded_gaps_scaled_by_delay_scale(
    tmp_path: Path, sleeps: list[float]
) -> None:
    text = breakdown().model_dump_json()
    write_cassette(
        tmp_path, cassette_key("S", "U"), [[0, text[:5]], [10, text[5:9]], [35, text[9:]]]
    )
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=2)
    [
        e
        async for e in p.stream(
            system="S", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
        )
    ]
    assert sleeps == pytest.approx([0, 0.02, 0.05])


async def test_synthetic_stream_chunks_text_with_scaled_delay(
    tmp_path: Path, sleeps: list[float]
) -> None:
    text = breakdown().model_dump_json()
    p = ReplayProvider(
        cassette_dir=tmp_path,
        fallback=[breakdown()],
        delay_scale=0.5,
        chunk_chars=10,
        chunk_delay=0.04,
    )
    events = [
        e
        async for e in p.stream(
            system="S", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
        )
    ]
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert [d.text for d in deltas] == [text[i : i + 10] for i in range(0, len(text), 10)]
    assert deltas[-1].snapshot == text
    assert sleeps == pytest.approx([0] + [0.02] * (len(deltas) - 1))
    final = events[-1]
    assert isinstance(final, LLMResult)
    assert final.usage.input_tokens == final.usage.output_tokens == 0
    assert (final.provider, final.model) == ("replay", "replay")
    assert cost_usd(final.model, final.usage) is None


async def test_fallback_choice_is_deterministic_per_prompt_pair(tmp_path: Path) -> None:
    fallback = [breakdown(project_name="Alpha"), breakdown(project_name="Beta")]
    p = ReplayProvider(cassette_dir=tmp_path, fallback=fallback, delay_scale=0)
    for user in ("one", "two", "three"):
        expected = fallback[int(cassette_key("S", user), 16) % 2]
        first = await p.generate(
            system="S",
            messages=[ChatMessage("user", user)],
            schema=EstimationBreakdown,
            cache_key="k",
        )
        again = await p.generate(
            system="S",
            messages=[ChatMessage("user", user)],
            schema=EstimationBreakdown,
            cache_key="k",
        )
        assert first.parsed == again.parsed == expected


async def test_a_conversation_replays_the_cassette_of_its_latest_message(tmp_path: Path) -> None:
    text = breakdown(project_name="Recorded").model_dump_json()
    write_cassette(tmp_path, cassette_key("S", "U"), [[0, text]])
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=0)
    history = [ChatMessage("user", "first"), ChatMessage("assistant", "{}"), *MESSAGES]
    result = await p.generate(
        system="S", messages=history, schema=EstimationBreakdown, cache_key="k"
    )
    assert result.parsed.project_name == "Recorded"


async def test_cassette_with_invalid_json_is_invalid_model_output(tmp_path: Path) -> None:
    write_cassette(tmp_path, cassette_key("S", "U"), [[0, '{"project_name": "Yo']])
    p = ReplayProvider(cassette_dir=tmp_path, fallback=[breakdown()], delay_scale=0)
    with pytest.raises(InvalidModelOutput):
        [
            e
            async for e in p.stream(
                system="S", messages=MESSAGES, schema=EstimationBreakdown, cache_key="k"
            )
        ]


def test_empty_fallback_fails_at_construction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fallback"):
        ReplayProvider(cassette_dir=tmp_path, fallback=[], delay_scale=0)
