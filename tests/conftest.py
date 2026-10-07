import pytest

from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from tests.factories import make_service
from tests.fakes import FakeProvider, SlowFakeProvider


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
