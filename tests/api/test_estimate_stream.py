import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi.testclient import TestClient

from app.services.errors import UpstreamUnavailable
from app.services.providers.base import StreamEvent, T, TextDelta
from app.services.providers.fallback import Cooldown, FallbackProvider
from tests.api.conftest import ClientFactory
from tests.factories import TRANSCRIPT
from tests.fakes import FakeProvider

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
    assert parse_sse(r.text)[-1][0] == "result"  # never a 200 with an empty body


def test_upstream_failure_becomes_an_error_event(client_with_failing_provider: TestClient) -> None:
    r = client_with_failing_provider.post(URL, json={"transcription": TRANSCRIPT})
    events = parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "upstream_unavailable" and events[-1][1]["retryable"] is True
    assert events[-1][1]["request_id"] == r.headers["x-request-id"]


class MalformedSnapshotsFake(FakeProvider):
    """Empty, broken and non-object snapshots before a valid final result."""

    snapshots = ("", "[1,", "garbage", '"just a string', "123", "null", '{"tasks": [{"id": ', "}{")

    async def stream(
        self, *, system: str, user: str, schema: type[T], cache_key: str
    ) -> AsyncGenerator[StreamEvent[T]]:
        for snapshot in self.snapshots:
            yield TextDelta(text=snapshot, snapshot=snapshot)
        async for event in super().stream(
            system=system, user=user, schema=schema, cache_key=cache_key
        ):
            if not isinstance(event, TextDelta):
                yield event


def test_malformed_partials_never_break_the_stream(make_client: ClientFactory) -> None:
    with make_client(provider=MalformedSnapshotsFake()) as client:
        events = parse_sse(client.post(URL, json={"transcription": TRANSCRIPT}).text)
    names = [e for e, _ in events]
    assert names[-1] == "result" and names.count("result") == 1 and "error" not in names


def test_primary_down_before_the_first_token_switches_to_the_fallback(
    make_client: ClientFactory,
) -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), model="gpt-4o-mini")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    with make_client(provider=FallbackProvider([primary, secondary], Cooldown())) as client:
        events = parse_sse(client.post(URL, json={"transcription": TRANSCRIPT}).text)
    statuses = [data for name, data in events if name == "status"]
    assert statuses[0] == {"phase": "calling_llm", "provider": "openai", "model": "gpt-4o-mini"}
    assert statuses[1] == {
        "phase": "fallback",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
    }
    name, result = events[-1]
    assert name == "result" and (result["provider"], result["model"]) == (
        "anthropic",
        "claude-haiku-4-5",
    )
    assert (result["metrics"]["fallback_used"], result["metrics"]["attempts"]) == (True, 2)


def test_primary_failing_after_tokens_is_an_error_never_a_mixed_answer(
    make_client: ClientFactory,
) -> None:
    primary = FakeProvider(stream_error_after_chunks=1, stream_error=UpstreamUnavailable())
    secondary = FakeProvider(name="anthropic")
    with make_client(provider=FallbackProvider([primary, secondary], Cooldown())) as client:
        events = parse_sse(client.post(URL, json={"transcription": TRANSCRIPT}).text)
    names = [name for name, _ in events]
    assert names[-1] == "error" and "result" not in names
    assert events[-1][1]["code"] == "upstream_unavailable"
    assert "fallback" not in [data["phase"] for name, data in events if name == "status"]
    assert secondary.calls == []
