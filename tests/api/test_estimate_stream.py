import json
from typing import Any

from fastapi.testclient import TestClient

from tests.factories import TRANSCRIPT

URL = "/api/v1/estimate/stream"


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        events.append((fields.get("event", "message"), json.loads(fields["data"])))
    return events


def test_stream_contract(client: TestClient) -> None:
    with client.stream("POST", URL, json={"transcription": TRANSCRIPT}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-accel-buffering"] == "no"
        events = parse_sse(r.read().decode())
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "result"
    assert names.count("result") + names.count("error") == 1
    assert "partial" in names


def test_over_limit_is_422_json_not_a_stream(client_with_limit_10: TestClient) -> None:
    r = client_with_limit_10.post(URL, json={"transcription": "x" * 11})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert client_with_limit_10.fake.calls == []


def test_at_limit_streams(client_with_limit_10: TestClient) -> None:
    r = client_with_limit_10.post(URL, json={"transcription": "x" * 10})
    assert r.status_code == 200


def test_upstream_failure_becomes_an_error_event(client_with_failing_provider: TestClient) -> None:
    r = client_with_failing_provider.post(URL, json={"transcription": TRANSCRIPT})
    events = parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "upstream_unavailable" and events[-1][1]["retryable"] is True
    assert events[-1][1]["request_id"] == r.headers["x-request-id"]
