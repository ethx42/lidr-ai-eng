from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self, TypeGuard, get_args

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Provider = Literal["openai", "anthropic", "replay"]
# Every level the installed SDKs define; which ones a model accepts lives in its profile.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def is_provider(name: str) -> TypeGuard[Provider]:
    return name in get_args(Provider)


def parse_link(entry: str) -> tuple[Provider, str]:
    """One `LLM_FALLBACKS` entry: `provider:model`."""
    name, _, model = (part.strip() for part in entry.partition(":"))
    if not is_provider(name) or not model:
        raise ValueError(
            f"LLM_FALLBACKS entry {entry.strip()!r} must be provider:model with provider one of "
            f"{', '.join(get_args(Provider))}"
        )
    return name, model


def parse_hosts(value: str | list[str]) -> list[str]:
    """`ALLOWED_HOSTS`: comma-separated host names. The port is never part of the match."""
    entries = value.split(",") if isinstance(value, str) else value
    hosts = [host.strip().lower() for host in entries if host.strip()]
    if not hosts or any(":" in host for host in hosts):
        raise ValueError(
            "ALLOWED_HOSTS must list host names without a port, e.g. localhost,ai-service"
        )
    return hosts


HostList = Annotated[list[str], NoDecode, BeforeValidator(parse_hosts)]


class Settings(BaseSettings):
    # Errors must not echo the raw input: it holds the API keys as plain strings.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    llm_provider: Provider = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    app_env: str = "development"
    log_level: str = "DEBUG"
    # Host header names the API answers (DNS rebinding guard): loopback for make run and make dev,
    # the Compose service name the BFF calls, and TestClient's default.
    allowed_hosts: HostList = ["localhost", "127.0.0.1", "ai-service", "testserver"]

    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    llm_max_output_tokens: int = Field(default=4096, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_reasoning_effort: ReasoningEffort | None = None
    max_transcription_chars: int = Field(default=50_000, gt=0)
    blended_hourly_rate: float | None = Field(default=None, gt=0)
    weekly_capacity_hours: float = Field(default=30, gt=0)
    replay_cassette_dir: Path = Path("tests/cassettes")
    replay_delay_scale: float = Field(default=1.0, ge=0)
    # Tried in order after the primary. `none` disables; so does "" as an init value, but an empty
    # environment value is ignored (env_ignore_empty) and keeps this default.
    llm_fallbacks: str = "anthropic:claude-haiku-4-5"
    llm_cooldown_failures: int = Field(default=3, gt=0)
    llm_cooldown_seconds: float = Field(default=30, ge=0)
    # Unset: no response cache (NullCache). Secret: the URL can carry a password.
    redis_url: SecretStr | None = None
    cache_ttl_seconds: int = Field(default=86_400, gt=0)

    @property
    def chain(self) -> list[tuple[Provider, str]]:
        """Primary first. Replay serves canned streams whatever LLM_MODEL says."""
        primary = (self.llm_provider, "replay" if self.llm_provider == "replay" else self.llm_model)
        fallbacks = self.llm_fallbacks.strip()
        if fallbacks.casefold() in ("", "none"):
            return [primary]
        return [primary, *(parse_link(entry) for entry in fallbacks.split(","))]

    def key_for(self, provider: Provider) -> str:
        key = {"openai": self.openai_api_key, "anthropic": self.anthropic_api_key}.get(provider)
        return key.get_secret_value().strip() if key else ""

    @property
    def api_key(self) -> str:
        return self.key_for(self.llm_provider)

    @model_validator(mode="after")
    def require_chain_keys(self) -> Self:
        missing = [
            f"{provider.upper()}_API_KEY is required "
            + (
                f"when LLM_PROVIDER={provider}"
                if position == 0
                else f"for the fallback {provider}:{model} (or set LLM_FALLBACKS=none)"
            )
            for position, (provider, model) in enumerate(self.chain)
            if provider != "replay" and not self.key_for(provider)
        ]
        if missing:
            raise ValueError("; ".join(missing))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
