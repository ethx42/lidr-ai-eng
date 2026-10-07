from fastapi.testclient import TestClient


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
