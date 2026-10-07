from itertools import product

import pytest

from app.prompts import loader
from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType
from tests.prompts.test_estimation_v1 import request

RULE = (
    "- Every client-facing surface the client mentions (mobile app, web app, customer portal, "
    "staff or admin panel, website) gets at least one frontend task of its own, even when the "
    "backend does most of the work.\n"
)


def test_v2_adds_the_frontend_coverage_rule() -> None:
    v1, _ = render_estimation_prompt(request(), version="v1")
    v2, _ = render_estimation_prompt(request(), version="v2")
    rule = "Every client-facing surface"
    assert rule not in v1 and rule in v2


@pytest.mark.parametrize(
    ("project_type", "detail_level", "output_format"),
    list(product(ProjectType, DetailLevel, OutputFormat)),
)
def test_v2_is_v1_plus_the_rule_only(
    project_type: ProjectType, detail_level: DetailLevel, output_format: OutputFormat
) -> None:
    # The eval delta between the versions must measure the rule and nothing else.
    typed = request(
        project_type=project_type, detail_level=detail_level, output_format=output_format
    )
    v1_system, v1_user = render_estimation_prompt(typed, version="v1")
    v2_system, v2_user = render_estimation_prompt(typed, version="v2")
    assert v2_user == v1_user
    assert v2_system.count(RULE) == 1
    assert v2_system.replace(RULE, "") == v1_system


def test_v2_includes_only_its_own_templates() -> None:
    source = (loader.PROMPTS_DIR / "estimation" / "v2" / "system.j2").read_text(encoding="utf-8")
    assert '{% include "estimation/v2/examples.j2" %}' in source
    assert "estimation/v1/" not in source
