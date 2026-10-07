from itertools import product

import pytest

from app.prompts.loader import available_versions
from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType
from app.services.llm_service import EstimationService
from tests.factories import typed_request

COMBINATIONS = list(product(ProjectType, DetailLevel, OutputFormat))


def test_cache_key_changes_with_enums(service_with_fake: EstimationService) -> None:
    a = service_with_fake.cache_key_for(typed_request(output_format="phases_table"))
    b = service_with_fake.cache_key_for(typed_request(output_format="narrative"))
    assert a != b


@pytest.mark.parametrize("version", available_versions())
@pytest.mark.parametrize(
    ("field", "value"),
    [("project_type", "mobile_app"), ("detail_level", "summary"), ("output_format", "line_items")],
)
def test_each_enum_is_part_of_the_cache_key(
    service_with_fake: EstimationService, version: str, field: str, value: str
) -> None:
    base = service_with_fake.cache_key_for(typed_request(), version)
    assert service_with_fake.cache_key_for(typed_request(**{field: value}), version) != base
    assert service_with_fake.cache_key_for(typed_request(), version) == base


@pytest.mark.parametrize("version", available_versions())
def test_every_enum_combination_has_its_own_key(
    service_with_fake: EstimationService, version: str
) -> None:
    # The key covers the enums only through the rendered prompt, while the markdown layout is
    # rendered in code from output_format: a template that merged enum blocks would let one
    # combination's cached response serve another.
    keys = {
        service_with_fake.cache_key_for(
            typed_request(project_type=p, detail_level=d, output_format=o), version
        )
        for p, d, o in COMBINATIONS
    }
    assert len(keys) == len(COMBINATIONS) == 36


def test_cache_key_changes_with_prompt_version(service_with_fake: EstimationService) -> None:
    request = typed_request()
    assert service_with_fake.cache_key_for(request, "v1") != service_with_fake.cache_key_for(
        request, "v2"
    )
