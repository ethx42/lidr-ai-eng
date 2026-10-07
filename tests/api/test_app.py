import json
import logging
from pathlib import Path

import pytest
from fastapi import APIRouter
from jinja2 import FileSystemLoader, UndefinedError

from app.main import create_app
from app.observability import JsonFormatter
from app.prompts import loader
from app.services.cache import NullCache
from tests.api.conftest import ClientFactory
from tests.factories import request_body
from tests.fakes import FakeProvider


def test_health(make_client: ClientFactory) -> None:
    with make_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": "0.1.0",
            "environment": "development",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "chain": ["openai:gpt-4o-mini"],
        }
        assert client.fake.calls == []


def test_health_reports_the_chain_that_serves(make_client: ClientFactory) -> None:
    with make_client(llm_provider="replay") as client:
        body = client.get("/health").json()
    assert (body["provider"], body["model"], body["chain"]) == (
        "replay",
        "replay",
        ["replay:replay"],
    )
    with make_client(anthropic_api_key="k", llm_fallbacks="anthropic:claude-haiku-4-5") as client:
        body = client.get("/health").json()
    assert body["chain"] == ["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"]


def test_docs_and_openapi(make_client: ClientFactory) -> None:
    with make_client() as client:
        assert client.get("/docs").status_code == 200
        spec = client.get("/openapi.json").json()
        assert spec["info"]["title"] == "CAG Software Estimator"
        assert spec["info"]["description"]
        operation = spec["paths"]["/api/v1/estimate"]["post"]
        assert "example" in operation["responses"]["200"]["content"]["application/json"]
        assert "Content-Type: application/json" in operation["description"]
        assert spec["components"]["schemas"]["EstimateRequest"]["examples"]


def test_request_id_propagated(make_client: ClientFactory) -> None:
    with make_client() as client:
        assert (
            client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
            == "abc-123"
        )


def test_request_id_generated_when_missing_or_unsafe(make_client: ClientFactory) -> None:
    with make_client() as client:
        generated = client.get("/health").headers["X-Request-ID"]
        assert len(generated) == 32
        unsafe = client.get("/health", headers={"X-Request-ID": "x" * 500}).headers["X-Request-ID"]
        assert unsafe != "x" * 500


def test_provider_created_once_and_closed_on_shutdown(make_client: ClientFactory) -> None:
    provider = FakeProvider()
    created: list[FakeProvider] = []

    def factory(_: object) -> FakeProvider:
        created.append(provider)
        return provider

    from fastapi.testclient import TestClient

    from app.config import Settings

    app = create_app(
        Settings(_env_file=None, openai_api_key="k", llm_fallbacks=""), provider_factory=factory
    )
    with TestClient(app) as client:
        for text in ("Client: one", "Client: two"):
            assert (
                client.post("/api/v1/estimate", json=request_body(transcription=text)).status_code
                == 200
            )
        assert not provider.closed
    assert len(created) == 1
    assert len(provider.calls) == 2
    assert provider.closed


def test_cache_closed_on_shutdown(make_client: ClientFactory) -> None:
    class ClosingCache(NullCache):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    cache = ClosingCache()
    with make_client(cache=cache) as client:
        assert client.post(
            "/api/v1/estimate", json=request_body(transcription="Client: one")
        ).is_success
        assert not cache.closed
    assert cache.closed


def test_unhandled_error_returns_json_500_with_request_id(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    with make_client() as client, caplog.at_level(logging.ERROR, logger="app.main"):
        boom = APIRouter()

        @boom.get("/boom")
        async def explode() -> None:
            raise RuntimeError("secret internals")

        client.app.include_router(boom)  # type: ignore[attr-defined]
        response = client.get("/boom", headers={"X-Request-ID": "r-500"})
        assert response.status_code == 500
        assert response.headers["X-Request-ID"] == "r-500"
        assert response.json() == {
            "error": {"code": "internal_error", "message": "Internal server error."},
            "request_id": "r-500",
        }
        assert "secret internals" not in response.text
    [record] = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exc_type"] == "RuntimeError"
    assert payload["request_id"] == "r-500"
    assert any(frame.endswith(" in explode") for frame in payload["stack"])
    assert "secret internals" not in json.dumps(payload)


def test_startup_fails_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.config import get_settings

    for var in ("OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir("/")  # no .env here
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="OPENAI_API_KEY"), TestClient(create_app()):
            pass
    finally:
        get_settings.cache_clear()


def test_startup_fails_on_an_unknown_prompt_version(make_client: ClientFactory) -> None:
    unknown = make_client(prompt_version="v999")
    with pytest.raises(ValueError, match="PROMPT_VERSION='v999'"), unknown:
        pass


def test_a_broken_template_fails_startup_not_the_first_request(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    version = tmp_path / "estimation" / "v1"
    version.mkdir(parents=True)
    (version / "system.j2").write_text("System.")
    (version / "user.j2").write_text("{{ transcript }} {{ typo_variable }}")
    monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
    monkeypatch.setattr(loader, "_env", loader._env.overlay(loader=FileSystemLoader(tmp_path)))
    with pytest.raises(UndefinedError, match="typo_variable"), make_client(prompt_version="v1"):
        pass


@pytest.mark.parametrize(
    "url",
    [
        "http://testserver/health",  # TestClient's default
        "http://localhost:8000/health",  # make run, make dev
        "http://127.0.0.1:8000/health",  # the Compose healthcheck
        "http://ai-service:8000/health",  # the BFF inside Compose
        "http://LOCALHOST:8000/health",
    ],
)
def test_allowed_hosts_are_answered(make_client: ClientFactory, url: str) -> None:
    with make_client() as client:
        assert client.get(url).status_code == 200


def test_foreign_host_is_rejected_before_any_handler(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # A page at rebind.attacker.example:8000 whose name now resolves to 127.0.0.1
    with make_client() as client, caplog.at_level(logging.WARNING, logger="app.main"):
        response = client.post(
            "http://rebind.attacker.example:8000/api/v1/estimate/stream?refresh=true",
            json=request_body(transcription="Client: one"),
            headers={"X-Request-ID": "r-host"},
        )
        assert response.status_code == 400
        assert response.headers["X-Request-ID"] == "r-host"
        assert response.json() == {
            "error": {"code": "invalid_host", "message": "Invalid host header."},
            "request_id": "r-host",
        }
        assert client.fake.calls == []
        for host in ("rebind.attacker.example", "localhost.attacker.example", ""):
            assert client.get("/health", headers={"host": host}).status_code == 400
    rejected = [r.fields["host"] for r in caplog.records if r.getMessage() == "host_rejected"]
    assert rejected == [
        "rebind.attacker.example",
        "rebind.attacker.example",
        "localhost.attacker.example",
        "",
    ]


def test_allowed_hosts_come_from_settings(make_client: ClientFactory) -> None:
    with make_client(allowed_hosts=["estimator.internal"]) as client:
        assert client.get("http://estimator.internal:8000/health").status_code == 200
        assert client.get("http://localhost:8000/health").status_code == 400
