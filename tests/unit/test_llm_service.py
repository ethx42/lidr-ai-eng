import logging

import pytest

from app.prompts.loader import load_prompt
from app.schemas.estimation import EstimateRequest
from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from tests.factories import TRANSCRIPT, breakdown
from tests.fakes import FakeProvider


def service(provider: FakeProvider, rate: float | None = None) -> EstimationService:
    return EstimationService(
        provider=provider, prompt=load_prompt(), weekly_capacity_hours=30, hourly_rate=rate
    )


async def test_estimate_pipeline() -> None:
    provider = FakeProvider()
    response = await service(provider, rate=100).estimate(
        EstimateRequest(transcription=TRANSCRIPT, output_language="Spanish")
    )
    assert response.breakdown.totals.expected_hours == 41.0
    assert response.breakdown.totals.estimated_cost == 4100.0
    assert "**Total estimated: 41.0 hours**" in response.estimation
    assert response.grounding.score == 1.0
    assert response.prompt_version == "v3"
    assert (response.provider, response.model) == ("openai", "fake-model")
    assert response.usage.cached_input_tokens == 1024
    [call] = provider.calls
    assert call["system"] == load_prompt().system_text
    assert TRANSCRIPT in call["user"]
    assert "<output_language>Spanish</output_language>" in call["user"]


async def test_system_prompt_identical_across_requests() -> None:
    provider = FakeProvider()
    svc = service(provider)
    await svc.estimate(EstimateRequest(transcription="Client: one", output_language="English"))
    await svc.estimate(EstimateRequest(transcription="Client: two"))
    assert provider.calls[0]["system"] == provider.calls[1]["system"]
    assert "Client: one" not in provider.calls[0]["system"]


async def test_grounding_flags_fabricated_requirement() -> None:
    fabricated = breakdown(
        requirements=[
            {"id": "R1", "statement": "Booking", "evidence": "a booking app"},
            {"id": "R2", "statement": "Loyalty", "evidence": "a loyalty program"},
        ]
    )
    response = await service(FakeProvider(result=fabricated)).estimate(
        EstimateRequest(transcription=TRANSCRIPT)
    )
    assert response.grounding.ungrounded_requirement_ids == ["R2"]
    assert "⚠ **R2**" in response.estimation


async def test_llm_call_logged_without_transcript(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        await service(FakeProvider()).estimate(EstimateRequest(transcription=TRANSCRIPT))
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "ok"  # type: ignore[attr-defined]
    assert record.fields["input_tokens"] == 1200  # type: ignore[attr-defined]
    for r in caplog.records:
        assert "yoga studio" not in str(r.__dict__)


async def test_provider_error_logged_and_raised(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), pytest.raises(UpstreamUnavailable):
        await service(FakeProvider(error=UpstreamUnavailable())).estimate(
            EstimateRequest(transcription=TRANSCRIPT)
        )
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "upstream_unavailable"  # type: ignore[attr-defined]
