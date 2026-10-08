from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.estimation import EstimationBreakdown
from app.services.cache import NullCache, ResponseCache
from app.services.errors import UpstreamUnavailable
from app.services.providers.base import ChatMessage, LLMProvider
from tests.factories import breakdown
from tests.fakes import FakeProvider

ClientFactory = Callable[..., Any]


@pytest.fixture
def make_client() -> ClientFactory:
    @contextmanager
    def factory(
        provider: LLMProvider | None = None, cache: ResponseCache | None = None, **values: Any
    ) -> Iterator[TestClient]:
        values = {"openai_api_key": "test-key", "llm_fallbacks": ""} | values
        settings = Settings(_env_file=None, **values)
        fake = provider or FakeProvider()
        app = create_app(
            settings,
            provider_factory=lambda _: fake,
            cache_factory=lambda _: cache or NullCache(),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            client.fake = fake  # type: ignore[attr-defined]
            yield client

    return factory


@pytest.fixture
def settings(request: pytest.FixtureRequest) -> Settings:
    """Override fields with indirect parametrization: `parametrize("settings", [{...}],
    indirect=True)`."""
    base = Settings(_env_file=None, openai_api_key="test-key", llm_fallbacks="")
    return base.model_copy(update=getattr(request, "param", {}))


@pytest.fixture
def client(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def client_with_limit_10(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client(max_transcription_chars=10) as test_client:
        yield test_client


@pytest.fixture
def client_with_failing_provider(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client(provider=FakeProvider(error=UpstreamUnavailable())) as test_client:
        yield test_client


@pytest.fixture
def app(settings: Settings, fake_provider: FakeProvider) -> FastAPI:
    return create_app(settings, provider_factory=lambda _: fake_provider)


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    # ASGITransport does not run the lifespan; the host must be one ALLOWED_HOSTS accepts.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        yield client


@pytest.fixture
def echo_provider(fake_provider: FakeProvider) -> FakeProvider:
    """Lists "Redsys" as a technology only when the last user message mentions it."""

    def respond(messages: Sequence[ChatMessage]) -> EstimationBreakdown:
        return breakdown(technologies=["Redsys"] if "Redsys" in messages[-1].content else [])

    fake_provider.respond_with = respond
    return fake_provider
