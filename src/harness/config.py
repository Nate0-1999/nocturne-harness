"""Harness configuration for the C.4 client and C.5 agent limits."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness.model_policy import parse_model_policy


class HarnessSettings(BaseSettings):
    """Spine access, provider keys, model selection, and bounded-run defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    spine_url: str = "http://localhost:8000"
    spine_token: SecretStr | None = None
    principal_id: str = Field(default="local", min_length=1)
    machine_id: str = Field(default="local-machine", min_length=1)
    agent_id: str = Field(default="harness-agent", min_length=1)
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    chat_model: str = "openrouter:minimax/minimax-m3"
    model_policy_chat: str | None = None
    model_context_tokens: int = Field(default=1_000_000, ge=1)
    run_request_limit: int = Field(default=40, ge=1)
    run_total_tokens_limit: int = Field(default=500_000, ge=1)
    label_max: int = Field(default=64, ge=1)
    extraction_idle_hours: float | None = Field(default=24.0, gt=0)

    @field_validator("model_context_tokens", mode="before")
    @classmethod
    def reject_boolean_context_window(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("model_context_tokens must be an integer")
        return value

    @field_validator("model_policy_chat")
    @classmethod
    def reject_blank_model_policy(cls, value: str | None) -> str | None:
        if value is not None:
            parse_model_policy(value)
        return value

    @property
    def effective_model_policy_chat(self) -> str:
        """Preserve static behavior when MODEL_POLICY_CHAT is unset."""

        return self.model_policy_chat or f"pinned:{self.chat_model}"
