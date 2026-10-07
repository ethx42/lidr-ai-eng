from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import Settings
from app.context.examples import REFERENCE_ESTIMATIONS
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.base import LLMProvider
from app.services.providers.openai_provider import OpenAIProvider, openai_http_client
from app.services.providers.profiles import get_profile
from app.services.providers.replay_provider import ReplayProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "replay":
        return ReplayProvider(
            cassette_dir=settings.replay_cassette_dir,
            fallback=[ref.estimation for ref in REFERENCE_ESTIMATIONS],
            delay_scale=settings.replay_delay_scale,
        )
    common = {
        "model": settings.llm_model,
        "profile": get_profile(
            settings.llm_model, settings.llm_provider, settings.llm_reasoning_effort
        ),
        "temperature": settings.llm_temperature,
        "reasoning_effort": settings.llm_reasoning_effort,
        "max_output_tokens": settings.llm_max_output_tokens,
    }
    client_options = {
        "api_key": settings.api_key,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(client=AsyncAnthropic(**client_options), **common)  # type: ignore[arg-type]
    client = AsyncOpenAI(**client_options, http_client=openai_http_client())  # type: ignore[arg-type]
    return OpenAIProvider(client=client, **common)  # type: ignore[arg-type]
