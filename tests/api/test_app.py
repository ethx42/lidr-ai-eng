import pytest
from fastapi import APIRouter

from app.main import create_app
from tests.api.conftest import ClientFactory
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
        }
        assert client.fake.calls == []


def test_docs_and_openapi(make_client: ClientFactory) -> None:
    with make_client() as client:
        assert client.get("/docs").status_code == 200
        spec = client.get("/openapi.json").json()
        assert spec["info"]["title"] == "CAG Software Estimator"
        assert spec["info"]["description"]
        operation = spec["paths"]["/api/v1/estimate"]["post"]
        assert "example" in operation["responses"]["200"]["content"]["application/json"]
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

    app = create_app(Settings(_env_file=None, openai_api_key="k"), provider_factory=factory)
    with TestClient(app) as client:
        for text in ("Client: one", "Client: two"):
            assert client.post("/api/v1/estimate", json={"transcription": text}).status_code == 200
        assert not provider.closed
    assert len(created) == 1
    assert len(provider.calls) == 2
    assert provider.closed


def test_unhandled_error_returns_json_500_with_request_id(make_client: ClientFactory) -> None:
    with make_client() as client:
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
