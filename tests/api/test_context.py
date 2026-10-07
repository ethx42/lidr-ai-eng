import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import ClientFactory


def test_context_exposes_prompt_and_references(client: TestClient) -> None:
    body = client.get("/api/v1/context").json()
    assert body["prompt_version"] and "<reference_estimations>" in body["system_prompt"]
    assert len(body["references"]) == 3 and body["chain"]


def test_context_reports_the_chain_and_the_transcription_limit(
    client_with_limit_10: TestClient,
) -> None:
    body = client_with_limit_10.get("/api/v1/context").json()
    assert body["chain"] == ["openai:gpt-4o-mini"]
    assert body["max_transcription_chars"] == 10
    assert client_with_limit_10.fake.calls == []


def test_context_chain_is_the_configured_chain(make_client: ClientFactory) -> None:
    with make_client(anthropic_api_key="k", llm_fallbacks="anthropic:claude-haiku-4-5") as client:
        body = client.get("/api/v1/context").json()
    assert body["chain"] == ["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"]


def test_context_renders_system_prompt_for_params(client: TestClient) -> None:
    r = client.get(
        "/api/v1/context",
        params={
            "project_type": "web_saas",
            "detail_level": "detailed",
            "output_format": "narrative",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "assumptions per phase" in body["system_prompt"]
    assert "phases_table" not in body["system_prompt"]
    assert body["available_versions"][0] == "v1"


def test_context_defaults_are_medium_phases_table(client: TestClient) -> None:
    body = client.get("/api/v1/context").json()
    assert "phases_table" in body["system_prompt"]


@pytest.mark.usefixtures("prompts_v99")
def test_context_defaults_to_the_configured_prompt_version(make_client: ClientFactory) -> None:
    with make_client(prompt_version="v99") as client:
        body = client.get("/api/v1/context").json()
        chosen = client.get("/api/v1/context", params={"prompt_version": "v1"}).json()
    assert (body["prompt_version"], body["available_versions"]) == ("v99", ["v1", "v99"])
    assert chosen["prompt_version"] == "v1"


@pytest.mark.parametrize(
    ("name", "value"),
    [("prompt_version", "v999"), ("prompt_version", "../v1"), ("output_format", "table")],
)
def test_context_rejects_unknown_params(client: TestClient, name: str, value: str) -> None:
    r = client.get("/api/v1/context", params={name: value})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert r.json()["error"]["details"][0]["loc"] == ["query", name]
