import logging
from dataclasses import dataclass
from typing import Any, Literal, get_args

from app.config import Provider, ReasoningEffort

logger = logging.getLogger(__name__)

Reasoning = Literal["none", "openai_effort", "anthropic_adaptive", "anthropic_budget"]

EFFORT_LEVELS: tuple[ReasoningEffort, ...] = get_args(ReasoningEffort)
ANTHROPIC_THINKING_BUDGET: dict[ReasoningEffort, int] = {
    "low": 2048,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "max": 32768,
}


def levels(*names: ReasoningEffort) -> frozenset[ReasoningEffort]:
    return frozenset(names)


GPT5_ORIGINAL = levels("minimal", "low", "medium", "high")
GPT5_1 = levels("none", "low", "medium", "high")
GPT5_X = GPT5_1 | levels("xhigh")
GPT5_6 = GPT5_X | levels("max")
O_SERIES = levels("low", "medium", "high")
CLAUDE_EFFORT = levels("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelProfile:
    provider: Provider
    supports_temperature: bool
    reasoning: Reasoning
    reasoning_token_headroom: int = 0
    efforts: frozenset[ReasoningEffort] = frozenset()


# Matched by longest model-id prefix. Checked against provider docs 2026-09; effort levels
# from a live probe of every listed family on 2026-09-23 (gpt-5.3 was not listed; it gets
# the gpt-5.2-5.5 set).
PROFILES: dict[str, ModelProfile] = {
    "gpt-4o": ModelProfile("openai", True, "none"),
    "gpt-4.1": ModelProfile("openai", True, "none"),
    "gpt-5": ModelProfile("openai", False, "openai_effort", 16384, GPT5_ORIGINAL),
    # Non-reasoning chat variant; temperature support not probed, so none is sent.
    "gpt-5-chat": ModelProfile("openai", False, "none"),
    "gpt-5.": ModelProfile("openai", False, "openai_effort", 16384, GPT5_X),
    "gpt-5.1": ModelProfile("openai", False, "openai_effort", 16384, GPT5_1),
    "gpt-5.6": ModelProfile("openai", False, "openai_effort", 16384, GPT5_6),
    "o3": ModelProfile("openai", False, "openai_effort", 16384, O_SERIES),
    "o4": ModelProfile("openai", False, "openai_effort", 16384, O_SERIES),
    "claude-haiku-4-5": ModelProfile(
        "anthropic", True, "anthropic_budget", 0, frozenset(ANTHROPIC_THINKING_BUDGET)
    ),
    "claude-sonnet-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384, CLAUDE_EFFORT),
    "claude-opus-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384, CLAUDE_EFFORT),
    "claude-fable-5": ModelProfile("anthropic", False, "anthropic_adaptive", 16384, CLAUDE_EFFORT),
}


def get_profile(
    model: str, provider: Provider, effort: ReasoningEffort | None = None
) -> ModelProfile:
    matches = [prefix for prefix in PROFILES if model.startswith(prefix)]
    if not matches:
        logger.warning(
            "No request profile for model %s; sending no sampling or reasoning parameters", model
        )
        return ModelProfile(provider, False, "none")
    profile = PROFILES[max(matches, key=len)]
    if effort and profile.reasoning != "none" and effort not in profile.efforts:
        supported = ", ".join(level for level in EFFORT_LEVELS if level in profile.efforts)
        logger.warning(
            "Model %s does not support reasoning effort %s (supported: %s); sending no effort",
            model,
            effort,
            supported,
        )
    return profile


def request_params(
    profile: ModelProfile,
    *,
    temperature: float,
    reasoning_effort: ReasoningEffort | None,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Provider request kwargs for sampling, reasoning, and output budget."""
    max_key = "max_output_tokens" if profile.provider == "openai" else "max_tokens"
    effort = reasoning_effort if reasoning_effort in profile.efforts else None
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
