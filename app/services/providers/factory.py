from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import Settings
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.base import LLMProvider
from app.services.providers.openai_provider import OpenAIProvider, openai_http_client
from app.services.providers.profiles import get_profile


def build_provider(settings: Settings) -> LLMProvider:
    common = {
        "model": settings.llm_model,
        "profile": get_profile(settings.llm_model, settings.llm_provider),
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
