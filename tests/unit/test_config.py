import pytest
from pydantic import ValidationError

from app.config import Settings

ENV_VARS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "APP_ENV",
    "LOG_LEVEL",
    "LLM_TEMPERATURE",
    "LLM_REASONING_EFFORT",
    "BLENDED_HOURLY_RATE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def load() -> Settings:
    return Settings(_env_file=None)


def test_defaults_with_only_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    settings = load()
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.app_env == "development"
    assert settings.log_level == "DEBUG"
    assert settings.llm_timeout_seconds == 60
    assert settings.llm_max_retries == 2
    assert settings.llm_max_output_tokens == 4096
    assert settings.llm_temperature == 0.2
    assert settings.llm_reasoning_effort is None
    assert settings.max_transcription_chars == 50_000
    assert settings.blended_hourly_rate is None
    assert settings.weekly_capacity_hours == 30


def test_missing_key_for_selected_provider_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        load()


def test_empty_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        load()


def test_unsupported_provider_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "acme")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    with pytest.raises(ValidationError, match="llm_provider"):
        load()


def test_empty_optional_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "")
    monkeypatch.setenv("BLENDED_HOURLY_RATE", "")
    settings = load()
    assert settings.llm_reasoning_effort is None
    assert settings.blended_hourly_rate is None


def test_keys_masked_in_repr_and_str(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-super-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    settings = load()
    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in settings.model_dump_json()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == secret


@pytest.mark.parametrize("level", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_all_sdk_effort_levels_accepted(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_REASONING_EFFORT", level)
    assert load().llm_reasoning_effort == level


def test_invalid_effort_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "extreme")
    with pytest.raises(ValidationError, match="llm_reasoning_effort"):
        load()
