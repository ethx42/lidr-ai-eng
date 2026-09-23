from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["openai", "anthropic"]
# Every level the installed SDKs define; which ones a model accepts lives in its profile.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    llm_provider: Provider = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    app_env: str = "development"
    log_level: str = "DEBUG"

    llm_timeout_seconds: float = Field(default=30, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    llm_max_output_tokens: int = Field(default=4096, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_reasoning_effort: ReasoningEffort | None = None
    max_transcription_chars: int = Field(default=50_000, gt=0)
    blended_hourly_rate: float | None = Field(default=None, gt=0)
    weekly_capacity_hours: float = Field(default=30, gt=0)

    @property
    def api_key(self) -> str:
        key = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        return key.get_secret_value().strip() if key else ""

    @model_validator(mode="after")
    def require_provider_key(self) -> Self:
        if not self.api_key:
            raise ValueError(
                f"{self.llm_provider.upper()}_API_KEY is required when "
                f"LLM_PROVIDER={self.llm_provider}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
