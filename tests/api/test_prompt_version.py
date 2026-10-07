import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import ClientFactory
from tests.api.test_estimate_stream import parse_sse
from tests.factories import request_body

PATHS = ["/api/v1/estimate", "/api/v1/estimate/stream"]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("bad", ["v999", "../v1", "v1/../../x", "V1", ""])
def test_bad_prompt_version_is_422_json(client: TestClient, path: str, bad: str) -> None:
    r = client.post(path, params={"prompt_version": bad}, json=request_body())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert r.json()["error"]["details"][0]["loc"] == ["query", "prompt_version"]
    assert client.fake.calls == []


def test_prompt_version_is_echoed(client: TestClient) -> None:
    r = client.post("/api/v1/estimate", params={"prompt_version": "v1"}, json=request_body())
    assert r.json()["prompt_version"] == "v1"


def served_version(client: TestClient, path: str, params: dict[str, str]) -> str:
    r = client.post(path, params=params, json=request_body())
    body = parse_sse(r.text)[-1][1] if path.endswith("/stream") else r.json()
    version: str = body["prompt_version"]
    return version


@pytest.mark.usefixtures("prompts_v99")
@pytest.mark.parametrize("path", PATHS)
def test_prompt_version_selects_the_templates(make_client: ClientFactory, path: str) -> None:
    with make_client(prompt_version="v99") as client:
        assert served_version(client, path, {}) == "v99"
        assert served_version(client, path, {"prompt_version": "v1"}) == "v1"
        keys = [call["cache_key"] for call in client.fake.calls]
    assert keys == ["estimator-v99", "estimator-v1"]
