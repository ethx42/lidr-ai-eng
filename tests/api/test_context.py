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
