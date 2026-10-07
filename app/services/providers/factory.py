from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import Provider, Settings
from app.context.examples import REFERENCE_ESTIMATIONS
from app.services.providers.anthropic_provider import AnthropicProvider, anthropic_http_client
from app.services.providers.base import LLMProvider
from app.services.providers.fallback import Cooldown, FallbackProvider
from app.services.providers.openai_provider import OpenAIProvider, openai_http_client
from app.services.providers.profiles import get_profile
from app.services.providers.replay_provider import ReplayProvider


def build_one(settings: Settings, provider: Provider, model: str, max_retries: int) -> LLMProvider:
    if provider == "replay":
        return ReplayProvider(
            cassette_dir=settings.replay_cassette_dir,
            fallback=[ref.estimation for ref in REFERENCE_ESTIMATIONS],
            delay_scale=settings.replay_delay_scale,
            model=model,
        )
    common = {
        "model": model,
        "profile": get_profile(model, provider, settings.llm_reasoning_effort),
        "temperature": settings.llm_temperature,
        "reasoning_effort": settings.llm_reasoning_effort,
        "max_output_tokens": settings.llm_max_output_tokens,
    }
    client_options = {
        "api_key": settings.key_for(provider),
        "timeout": settings.llm_timeout_seconds,
        "max_retries": max_retries,
    }
    if provider == "anthropic":
        anthropic_client = AsyncAnthropic(**client_options, http_client=anthropic_http_client())  # type: ignore[arg-type]  # mixed-value options dict
        return AnthropicProvider(client=anthropic_client, **common)  # type: ignore[arg-type]  # mixed-value kwargs dict
    client = AsyncOpenAI(**client_options, http_client=openai_http_client())  # type: ignore[arg-type]
    return OpenAIProvider(client=client, **common)  # type: ignore[arg-type]


def build_provider(settings: Settings) -> FallbackProvider:
    """Always the router, even over one provider, so logs and metrics have one shape. Only the last
    provider keeps SDK retries: before it, the router's next provider is the retry, so a primary
    that fails before its first token hands over after one timeout, not after every retry."""
    chain = settings.chain
    return FallbackProvider(
        [
            build_one(settings, provider, model, settings.llm_max_retries if n == len(chain) else 0)
            for n, (provider, model) in enumerate(chain, start=1)
        ],
        Cooldown(failures=settings.llm_cooldown_failures, seconds=settings.llm_cooldown_seconds),
    )
