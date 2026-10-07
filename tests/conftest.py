import pytest

from app.prompts.loader import load_prompt
from app.services.llm_service import EstimationService
from tests.fakes import FakeProvider


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def service_with_fake(fake: FakeProvider) -> EstimationService:
    return EstimationService(
        provider=fake, prompt=load_prompt(), weekly_capacity_hours=30, hourly_rate=None
    )
