"""Pydantic settings for AI-Army configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    github_token: str = ""
    github_target_repo: str = ""

    # Optional fallback
    openai_api_key: str | None = None


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


settings = get_settings()
