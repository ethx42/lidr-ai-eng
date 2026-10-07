import pytest

from app.services.llm_service import EstimationService
from tests.factories import typed_request


def test_cache_key_changes_with_enums(service_with_fake: EstimationService) -> None:
    a = service_with_fake.cache_key_for(typed_request(output_format="phases_table"))
    b = service_with_fake.cache_key_for(typed_request(output_format="narrative"))
    assert a != b


@pytest.mark.parametrize(
    ("field", "value"),
    [("project_type", "mobile_app"), ("detail_level", "summary"), ("output_format", "line_items")],
)
def test_each_enum_is_part_of_the_cache_key(
    service_with_fake: EstimationService, field: str, value: str
) -> None:
    base = service_with_fake.cache_key_for(typed_request())
    assert service_with_fake.cache_key_for(typed_request(**{field: value})) != base
    assert service_with_fake.cache_key_for(typed_request()) == base
