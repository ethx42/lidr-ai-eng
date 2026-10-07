from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.errors import UpstreamUnavailable
from tests.fakes import FakeProvider

ClientFactory = Callable[..., Any]


@pytest.fixture
def make_client() -> ClientFactory:
    @contextmanager
    def factory(provider: FakeProvider | None = None, **values: Any) -> Iterator[TestClient]:
        settings = Settings(_env_file=None, openai_api_key="test-key", **values)
        fake = provider or FakeProvider()
        app = create_app(settings, provider_factory=lambda _: fake)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.fake = fake  # type: ignore[attr-defined]
            yield client

    return factory


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key")


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
