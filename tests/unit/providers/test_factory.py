import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.context.examples import REFERENCE_ESTIMATIONS
from app.services.providers.anthropic_provider import AnthropicProvider, _no_retry_on_spend_cap
from app.services.providers.factory import build_provider
from app.services.providers.openai_provider import OpenAIProvider, _no_retry_on_quota
from app.services.providers.replay_provider import ReplayProvider


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "REPLAY_CASSETTE_DIR",
        "REPLAY_DELAY_SCALE",
    ):
        monkeypatch.delenv(var, raising=False)


async def test_openai_selected() -> None:
    provider = build_provider(settings(openai_api_key="k"))
    assert isinstance(provider, OpenAIProvider)
    assert (provider.name, provider.model) == ("openai", "gpt-4o-mini")
    assert provider.client.max_retries == 2
    assert provider.client.timeout == 60
    assert _no_retry_on_quota in provider.client._client.event_hooks["response"]
    await provider.aclose()


async def test_anthropic_selected() -> None:
    provider = build_provider(
        settings(llm_provider="anthropic", llm_model="claude-haiku-4-5", anthropic_api_key="k")
    )
    assert isinstance(provider, AnthropicProvider)
    assert (provider.name, provider.model) == ("anthropic", "claude-haiku-4-5")
    assert _no_retry_on_spend_cap in provider.client._client.event_hooks["response"]
    await provider.aclose()


async def test_replay_selected_without_any_key(tmp_path: Path) -> None:
    provider = build_provider(
        settings(llm_provider="replay", replay_cassette_dir=tmp_path, replay_delay_scale=0)
    )
    assert isinstance(provider, ReplayProvider)
    assert (provider.name, provider.model) == ("replay", "replay")
    assert (provider.cassette_dir, provider.delay_scale) == (tmp_path, 0)
    assert provider.fallback == [ref.estimation for ref in REFERENCE_ESTIMATIONS]
    await provider.aclose()


async def test_unsupported_effort_warned_at_startup_and_not_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        provider = build_provider(
            settings(
                llm_provider="anthropic",
                llm_model="claude-opus-5",
                llm_reasoning_effort="minimal",
                anthropic_api_key="k",
            )
        )
    assert "claude-opus-5" in caplog.text
    assert isinstance(provider, AnthropicProvider)
    assert not {"thinking", "output_config"} & provider.params.keys()
    await provider.aclose()
