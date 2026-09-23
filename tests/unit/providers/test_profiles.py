import logging

import pytest

from app.services.providers.profiles import get_profile, request_params


@pytest.mark.parametrize(
    "model,effort,expected",
    [
        ("gpt-4o-mini", None, {"max_output_tokens": 4096, "temperature": 0.2}),
        ("gpt-4o-mini", "high", {"max_output_tokens": 4096, "temperature": 0.2}),
        ("gpt-4.1", None, {"max_output_tokens": 4096, "temperature": 0.2}),
        ("gpt-5-mini", None, {"max_output_tokens": 4096 + 16384}),
        (
            "gpt-5.2",
            "medium",
            {"max_output_tokens": 4096 + 16384, "reasoning": {"effort": "medium"}},
        ),
        ("o4-mini", "low", {"max_output_tokens": 4096 + 16384, "reasoning": {"effort": "low"}}),
        ("claude-haiku-4-5", None, {"max_tokens": 4096, "temperature": 0.2}),
        (
            "claude-haiku-4-5-20251001",
            "medium",
            {"max_tokens": 4096 + 4096, "thinking": {"type": "enabled", "budget_tokens": 4096}},
        ),
        ("claude-opus-5", None, {"max_tokens": 4096}),
        (
            "claude-opus-5-5",
            "high",
            {
                "max_tokens": 4096 + 16384,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "high"},
            },
        ),
        ("claude-sonnet-5", None, {"max_tokens": 4096}),
        ("acme-llm-1", "high", {"max_output_tokens": 4096}),
    ],
)
def test_request_params_per_profile(
    model: str, effort: str | None, expected: dict[str, object]
) -> None:
    provider = "anthropic" if model.startswith("claude") else "openai"
    profile = get_profile(model, provider)
    params = request_params(
        profile, temperature=0.2, reasoning_effort=effort, max_output_tokens=4096
    )
    assert params == expected


def test_longest_prefix_wins() -> None:
    assert get_profile("gpt-4o-mini", "openai").supports_temperature
    assert not get_profile("gpt-5-nano", "openai").supports_temperature


def test_unknown_model_is_conservative_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        profile = get_profile("acme-llm-1", "anthropic")
    assert not profile.supports_temperature
    assert profile.reasoning == "none"
    assert "acme-llm-1" in caplog.text
    params = request_params(profile, temperature=0.2, reasoning_effort="high", max_output_tokens=10)
    assert params == {"max_tokens": 10}
