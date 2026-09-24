from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
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
