import logging

import pytest

from app.services.errors import (
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from tests.api.conftest import ClientFactory
from tests.factories import TRANSCRIPT
from tests.fakes import FakeProvider

URL = "/api/v1/estimate"


def test_success(make_client: ClientFactory) -> None:
    with make_client() as client:
        response = client.post(URL, json={"transcription": TRANSCRIPT})
        assert response.status_code == 200
        body = response.json()
        assert body["estimation"].startswith("## Estimation:")
        assert isinstance(body["model"], str)
        assert body["provider"] == "openai"
        assert body["prompt_version"] == "v3"
        assert len(body["breakdown"]["tasks"]) >= 1
        assert body["breakdown"]["totals"]["expected_hours"] == 41.0
        assert [t["expected_hours"] for t in body["breakdown"]["tasks"]] == [11.0, 30.0]
        assert body["grounding"]["score"] == 1.0
        assert body["usage"] == {
            "input_tokens": 1200,
            "output_tokens": 800,
            "cached_input_tokens": 1024,
        }


def test_llm_call_log_excludes_transcript(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    with make_client() as client, caplog.at_level(logging.DEBUG):
        client.post(URL, json={"transcription": TRANSCRIPT}, headers={"X-Request-ID": "log-1"})
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert record.request_id == "log-1"  # type: ignore[attr-defined]
    assert all("yoga studio" not in str(r.__dict__) for r in caplog.records)


@pytest.mark.parametrize(
    "payload,settings",
    [
        ({"transcription": "   "}, {}),
        ({"transcription": ""}, {}),
        ({}, {}),
        ({"transcription": "x" * 11}, {"max_transcription_chars": 10}),
        ({"transcription": "hello", "model": "gpt-5"}, {}),
    ],
    ids=["whitespace", "empty", "missing", "too-long", "extra-field"],
)
def test_validation_422_without_provider_call(
    make_client: ClientFactory, payload: dict[str, object], settings: dict[str, object]
) -> None:
    with make_client(**settings) as client:
        response = client.post(URL, json=payload, headers={"X-Request-ID": "v-1"})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "invalid_request"
        assert body["request_id"] == "v-1"
        assert client.fake.calls == []


def test_422_does_not_echo_transcription(make_client: ClientFactory) -> None:
    with make_client(max_transcription_chars=10) as client:
        response = client.post(URL, json={"transcription": "SECRET-MEETING-CONTENT"})
        assert response.status_code == 422
        assert "SECRET-MEETING-CONTENT" not in response.text


@pytest.mark.parametrize(
    "error,status,code",
    [
        (UpstreamRateLimited(), 429, "upstream_rate_limited"),
        (UpstreamUnavailable(), 503, "upstream_unavailable"),
        (InvalidModelOutput(), 502, "invalid_model_output"),
        (UpstreamError(), 502, "upstream_error"),
        (UpstreamError("quota"), 502, "upstream_error"),
    ],
)
def test_upstream_error_mapping(
    make_client: ClientFactory, error: LLMError, status: int, code: str
) -> None:
    with make_client(provider=FakeProvider(error=error)) as client:
        response = client.post(
            URL, json={"transcription": TRANSCRIPT}, headers={"X-Request-ID": "e-1"}
        )
        assert response.status_code == status
        assert response.json() == {
            "error": {"code": code, "message": error.message},
            "request_id": "e-1",
        }
        assert response.headers["X-Request-ID"] == "e-1"
