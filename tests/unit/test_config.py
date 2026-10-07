from pathlib import Path

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
    "REPLAY_CASSETTE_DIR",
    "REPLAY_DELAY_SCALE",
    "LLM_FALLBACKS",
    "LLM_COOLDOWN_FAILURES",
    "LLM_COOLDOWN_SECONDS",
    "ALLOWED_HOSTS",
    "PROMPT_VERSION",
    "MAX_TURNS",
    "MAX_HISTORY_CHARS",
    "SESSION_TTL_SECONDS",
    "MAX_SESSIONS",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def load() -> Settings:
    return Settings(_env_file=None)


def test_defaults_with_only_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
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
    assert settings.prompt_version == "v2"
    assert settings.max_turns == 6
    assert settings.max_history_chars == 60_000
    assert settings.session_ttl_seconds == 7200
    assert settings.max_sessions == 1000


@pytest.mark.parametrize(
    "var", ["MAX_TURNS", "MAX_HISTORY_CHARS", "SESSION_TTL_SECONDS", "MAX_SESSIONS"]
)
def test_non_positive_session_limits_rejected(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    monkeypatch.setenv(var, "0")
    with pytest.raises(ValidationError, match=var.lower()):
        load()


def test_replay_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    settings = load()
    assert settings.llm_provider == "replay"
    assert settings.chain == [("replay", "replay")]  # replay ignores LLM_MODEL
    assert settings.replay_cassette_dir == Path("tests/cassettes")
    assert settings.replay_delay_scale == 1.0


def test_negative_replay_delay_scale_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("REPLAY_DELAY_SCALE", "-1")
    with pytest.raises(ValidationError, match="replay_delay_scale"):
        load()


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
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "")
    monkeypatch.setenv("BLENDED_HOURLY_RATE", "")
    settings = load()
    assert settings.llm_reasoning_effort is None
    assert settings.blended_hourly_rate is None


def test_keys_masked_in_repr_and_str(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-super-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    settings = load()
    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in settings.model_dump_json()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == secret


def test_startup_errors_never_echo_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-super-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)  # the default fallback's key is missing
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY") as info:
        load()
    assert secret not in str(info.value) and secret not in repr(info.value)


@pytest.mark.parametrize("level", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_all_sdk_effort_levels_accepted(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    monkeypatch.setenv("LLM_REASONING_EFFORT", level)
    assert load().llm_reasoning_effort == level


def test_invalid_effort_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "extreme")
    with pytest.raises(ValidationError, match="llm_reasoning_effort"):
        load()


def both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")


def test_default_chain_falls_back_to_claude_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    both_keys(monkeypatch)
    settings = load()
    assert settings.llm_fallbacks == "anthropic:claude-haiku-4-5"
    assert (settings.llm_cooldown_failures, settings.llm_cooldown_seconds) == (3, 30)
    assert settings.chain == [("openai", "gpt-4o-mini"), ("anthropic", "claude-haiku-4-5")]
    keys = [settings.key_for(p) for p in ("openai", "anthropic", "replay")]
    assert keys == ["test-openai", "test-anthropic", ""]


def test_chain_parses_comma_separated_provider_model_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv(
        "LLM_FALLBACKS", " openai:gpt-4.1-mini , anthropic:claude-haiku-4-5,replay:replay"
    )
    assert load().chain == [
        ("anthropic", "claude-sonnet-4-5"),
        ("openai", "gpt-4.1-mini"),
        ("anthropic", "claude-haiku-4-5"),
        ("replay", "replay"),
    ]


def test_missing_fallback_key_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY") as info:
        load()
    assert "LLM_FALLBACKS=none" in str(info.value)  # says how to run without a fallback


@pytest.mark.parametrize("value", ["none", "None", " NONE "])
def test_none_disables_fallback(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", value)
    assert load().chain == [("openai", "gpt-4o-mini")]


def test_empty_init_value_disables_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    assert Settings(_env_file=None, llm_fallbacks="").chain == [("openai", "gpt-4o-mini")]


def test_empty_env_value_keeps_the_default_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    both_keys(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACKS", "")
    assert load().chain == [("openai", "gpt-4o-mini"), ("anthropic", "claude-haiku-4-5")]


@pytest.mark.parametrize("value", ["acme:model-1", "anthropic", "anthropic:", ":gpt-4o-mini", ","])
def test_unknown_or_malformed_fallback_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    both_keys(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACKS", value)
    with pytest.raises(ValidationError, match="LLM_FALLBACKS"):
        load()


def test_replay_in_the_chain_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "replay:replay")
    assert load().chain == [("openai", "gpt-4o-mini"), ("replay", "replay")]


@pytest.mark.parametrize(
    ("var", "value"), [("LLM_COOLDOWN_FAILURES", "0"), ("LLM_COOLDOWN_SECONDS", "-1")]
)
def test_invalid_cooldown_rejected(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    both_keys(monkeypatch)
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError, match=var.lower()):
        load()


def test_allowed_hosts_default_covers_loopback_compose_and_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    assert load().allowed_hosts == ["localhost", "127.0.0.1", "ai-service", "testserver"]
    monkeypatch.setenv("ALLOWED_HOSTS", "")  # an empty value keeps the default
    assert load().allowed_hosts == ["localhost", "127.0.0.1", "ai-service", "testserver"]


def test_allowed_hosts_parses_comma_separated_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    monkeypatch.setenv("ALLOWED_HOSTS", " Estimator.internal ,127.0.0.1,")
    assert load().allowed_hosts == ["estimator.internal", "127.0.0.1"]


@pytest.mark.parametrize("value", ["localhost:8000", ",", "localhost, ai-service:8000"])
def test_allowed_hosts_with_a_port_or_no_name_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("LLM_FALLBACKS", "none")
    monkeypatch.setenv("ALLOWED_HOSTS", value)
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        load()
