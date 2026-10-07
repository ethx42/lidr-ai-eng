import pytest

from app.prompts.loader import load_prompt
from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from tests.fakes import FakeProvider, SlowFakeProvider


def make_service(provider: FakeProvider) -> EstimationService:
    return EstimationService(
        provider=provider, prompt=load_prompt(), weekly_capacity_hours=30, hourly_rate=None
    )


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def service_with_fake(fake: FakeProvider) -> EstimationService:
    return make_service(fake)


@pytest.fixture
def slow_fake() -> SlowFakeProvider:
    return SlowFakeProvider()


@pytest.fixture
def service_with_slow_fake(slow_fake: SlowFakeProvider) -> EstimationService:
    return make_service(slow_fake)


@pytest.fixture
def service_with_failing_fake() -> EstimationService:
    return make_service(FakeProvider(error=UpstreamUnavailable()))
