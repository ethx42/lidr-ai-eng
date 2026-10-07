import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.context.examples import REFERENCE_ESTIMATIONS
from app.services.providers.anthropic_provider import AnthropicProvider, _no_retry_on_spend_cap
from app.services.providers.factory import build_provider
from app.services.providers.fallback import FallbackProvider
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
        "LLM_FALLBACKS",
        "LLM_COOLDOWN_FAILURES",
        "LLM_COOLDOWN_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)


async def test_openai_selected() -> None:
    provider = build_provider(settings(openai_api_key="k", llm_fallbacks="")).chain[0]
    assert isinstance(provider, OpenAIProvider)
    assert (provider.name, provider.model) == ("openai", "gpt-4o-mini")
    assert provider.client.max_retries == 2
    assert provider.client.timeout == 60
    assert _no_retry_on_quota in provider.client._client.event_hooks["response"]
    await provider.aclose()


async def test_anthropic_selected() -> None:
    provider = build_provider(
        settings(llm_provider="anthropic", llm_model="claude-haiku-4-5", anthropic_api_key="k")
    ).chain[0]
    assert isinstance(provider, AnthropicProvider)
    assert (provider.name, provider.model) == ("anthropic", "claude-haiku-4-5")
    assert _no_retry_on_spend_cap in provider.client._client.event_hooks["response"]
    await provider.aclose()


async def test_replay_selected_without_any_key(tmp_path: Path) -> None:
    provider = build_provider(
        settings(
            llm_provider="replay",
            replay_cassette_dir=tmp_path,
            replay_delay_scale=0,
            llm_fallbacks="none",
        )
    ).chain[0]
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
        ).chain[0]
    assert "claude-opus-5" in caplog.text
    assert isinstance(provider, AnthropicProvider)
    assert not {"thinking", "output_config"} & provider.params.keys()
    await provider.aclose()


async def test_default_chain_gives_each_provider_its_key_and_the_settings_cooldown() -> None:
    router = build_provider(
        settings(
            openai_api_key="key-openai",
            anthropic_api_key="key-anthropic",
            llm_cooldown_failures=5,
            llm_cooldown_seconds=12,
        )
    )
    assert isinstance(router, FallbackProvider)
    assert (router.name, router.model) == ("openai", "gpt-4o-mini")
    primary, fallback = router.chain
    assert isinstance(primary, OpenAIProvider) and primary.client.api_key == "key-openai"
    assert isinstance(fallback, AnthropicProvider) and fallback.client.api_key == "key-anthropic"
    assert fallback.model == "claude-haiku-4-5"
    assert (fallback.client.max_retries, fallback.client.timeout) == (2, 60)
    assert _no_retry_on_spend_cap in fallback.client._client.event_hooks["response"]
    assert (router.cooldown.failures, router.cooldown.seconds) == (5, 12)
    await router.aclose()


async def test_a_single_provider_is_still_wrapped() -> None:
    router = build_provider(settings(openai_api_key="k", llm_fallbacks="none"))
    assert isinstance(router, FallbackProvider) and len(router.chain) == 1
    await router.aclose()


async def test_replay_can_be_a_fallback(tmp_path: Path) -> None:
    router = build_provider(
        settings(openai_api_key="k", llm_fallbacks="replay:replay", replay_cassette_dir=tmp_path)
    )
    replay = router.chain[1]
    assert isinstance(replay, ReplayProvider)
    assert (replay.name, replay.model, replay.cassette_dir) == ("replay", "replay", tmp_path)
    await router.aclose()


async def test_only_the_last_provider_keeps_sdk_retries() -> None:
    router = build_provider(
        settings(
            openai_api_key="k",
            anthropic_api_key="k",
            llm_fallbacks="anthropic:claude-haiku-4-5,openai:gpt-4.1-mini",
            llm_max_retries=3,
        )
    )
    retries = [provider.client.max_retries for provider in router.chain]
    assert retries == [0, 0, 3]  # the router retries on the next provider instead
    assert all(provider.client.timeout == 60 for provider in router.chain)
    await router.aclose()


async def test_a_single_provider_keeps_the_configured_sdk_retries() -> None:
    router = build_provider(settings(openai_api_key="k", llm_fallbacks="none", llm_max_retries=3))
    assert router.chain[0].client.max_retries == 3
    await router.aclose()
