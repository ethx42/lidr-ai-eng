import pytest

from app.config import Settings
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.factory import build_provider
from app.services.providers.openai_provider import OpenAIProvider


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LLM_PROVIDER", "LLM_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


async def test_openai_selected() -> None:
    provider = build_provider(settings(openai_api_key="k"))
    assert isinstance(provider, OpenAIProvider)
    assert (provider.name, provider.model) == ("openai", "gpt-4o-mini")
    assert provider.client.max_retries == 2
    assert provider.client.timeout == 30
    await provider.aclose()


async def test_anthropic_selected() -> None:
    provider = build_provider(
        settings(llm_provider="anthropic", llm_model="claude-haiku-4-5", anthropic_api_key="k")
    )
    assert isinstance(provider, AnthropicProvider)
    assert (provider.name, provider.model) == ("anthropic", "claude-haiku-4-5")
    await provider.aclose()
