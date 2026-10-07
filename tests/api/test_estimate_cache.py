from typing import Any

import fakeredis
import httpx2
import pytest

from app.services.cache import RedisCache
from tests.api.conftest import ClientFactory
from tests.api.test_estimate_stream import parse_sse
from tests.factories import TRANSCRIPT, breakdown
from tests.fakes import FakeProvider

ESTIMATE = "/api/v1/estimate"
STREAM = "/api/v1/estimate/stream"
BODY = {"transcription": TRANSCRIPT}


def result_of(response: httpx2.Response) -> dict[str, Any]:
    assert response.status_code == 200
    if response.headers["content-type"].startswith("text/event-stream"):
        event, data = parse_sse(response.text)[-1]
        assert event == "result"
        return data
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize("url", [ESTIMATE, STREAM])
def test_refresh_regenerates_and_overwrites_the_cached_entry(
    url: str, make_client: ClientFactory, redis_client: fakeredis.FakeAsyncRedis
) -> None:
    fake = FakeProvider()
    with make_client(provider=fake, cache=RedisCache(redis_client, ttl_seconds=60)) as client:
        assert result_of(client.post(url, json=BODY))["metrics"]["cache_hit"] is False
        assert result_of(client.post(url, json=BODY))["metrics"]["cache_hit"] is True
        fake.result = breakdown(project_name="Regenerated")
        fresh = result_of(client.post(url, params={"refresh": "true"}, json=BODY))
        cached = result_of(client.post(url, json=BODY))
    assert len(fake.calls) == 2
    assert fresh["metrics"]["cache_hit"] is False
    assert cached["metrics"]["cache_hit"] is True
    assert cached["breakdown"]["project_name"] == "Regenerated"


def test_a_stream_cache_hit_is_a_status_then_the_result(
    make_client: ClientFactory, redis_client: fakeredis.FakeAsyncRedis
) -> None:
    with make_client(cache=RedisCache(redis_client, ttl_seconds=60)) as client:
        client.post(ESTIMATE, json=BODY)
        events = parse_sse(client.post(STREAM, json=BODY).text)
    assert [(name, data.get("phase")) for name, data in events] == [
        ("status", "cache_hit"),
        ("result", None),
    ]
    assert events[-1][1]["metrics"]["cache_hit"] is True
