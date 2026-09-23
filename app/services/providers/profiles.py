import logging
from dataclasses import dataclass
from typing import Any, Literal

from app.config import Provider, ReasoningEffort

logger = logging.getLogger(__name__)

Reasoning = Literal["none", "openai_effort", "anthropic_adaptive", "anthropic_budget"]

ANTHROPIC_THINKING_BUDGET: dict[ReasoningEffort, int] = {"low": 2048, "medium": 4096, "high": 8192}


@dataclass(frozen=True)
class ModelProfile:
    provider: Provider
    supports_temperature: bool
    reasoning: Reasoning
    reasoning_token_headroom: int = 0


# Matched by longest model-id prefix. Checked against provider docs 2026-09.
PROFILES: dict[str, ModelProfile] = {
    "gpt-4o": ModelProfile("openai", True, "none"),
    "gpt-4.1": ModelProfile("openai", True, "none"),
    "gpt-5": ModelProfile("openai", False, "openai_effort", 16384),
    "o3": ModelProfile("openai", False, "openai_effort", 16384),
    "o4": ModelProfile("openai", False, "openai_effort", 16384),
    "claude-haiku-4-5": ModelProfile("anthropic", True, "anthropic_budget"),
    "claude-sonnet-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384),
    "claude-opus-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384),
    "claude-fable-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384),
}


def get_profile(model: str, provider: Provider) -> ModelProfile:
    matches = [prefix for prefix in PROFILES if model.startswith(prefix)]
    if matches:
        return PROFILES[max(matches, key=len)]
    logger.warning(
        "No request profile for model %s; sending no sampling or reasoning parameters", model
    )
    return ModelProfile(provider, False, "none")


def request_params(
    profile: ModelProfile,
    *,
    temperature: float,
    reasoning_effort: ReasoningEffort | None,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Provider request kwargs for sampling, reasoning, and output budget."""
    max_key = "max_output_tokens" if profile.provider == "openai" else "max_tokens"
    effort = reasoning_effort if profile.reasoning != "none" else None
    # OpenAI reasoning models always reason; Claude thinks only when configured.
    always_reasons = profile.reasoning == "openai_effort"
    params: dict[str, Any] = {
        max_key: max_output_tokens + (profile.reasoning_token_headroom if always_reasons else 0)
    }

    match profile.reasoning, effort:
        case "openai_effort", str():
            params["reasoning"] = {"effort": effort}
        case "anthropic_adaptive", str():
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": effort}
            params[max_key] = max_output_tokens + profile.reasoning_token_headroom
        case "anthropic_budget", str():
            budget = ANTHROPIC_THINKING_BUDGET[effort]
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params[max_key] = max_output_tokens + budget
        case _:
            pass

    if profile.supports_temperature and "thinking" not in params:
        params["temperature"] = temperature
    return params
