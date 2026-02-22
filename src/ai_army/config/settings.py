"""Pydantic settings for AI-Army configuration."""

import os
from dataclasses import dataclass
from typing import Iterator

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class GitHubRepoConfig:
    """Configuration for a single GitHub repo."""

    token: str
    repo: str


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    openai_api_key: str | None = None

    # Single repo (backward compat)
    github_token: str = ""
    github_target_repo: str = ""

    # Multi-repo: GITHUB_REPO_1, GITHUB_TOKEN_1, GITHUB_REPO_2, GITHUB_TOKEN_2, ...
    # Loaded dynamically - see get_github_repos()


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


settings = get_settings()


def get_github_repos() -> list[GitHubRepoConfig]:
    """Get list of GitHub repo configs from env.

    Supports:
    - Single: GITHUB_TOKEN, GITHUB_TARGET_REPO
    - Multi: GITHUB_REPO_1, GITHUB_TOKEN_1, GITHUB_REPO_2, GITHUB_TOKEN_2, ...
    """
    configs: list[GitHubRepoConfig] = []

    # Check numbered repos first (GITHUB_REPO_1, GITHUB_TOKEN_1, ...)
    n = 1
    while True:
        repo = os.getenv(f"GITHUB_REPO_{n}")
        token = os.getenv(f"GITHUB_TOKEN_{n}")
        if repo and token:
            configs.append(GitHubRepoConfig(token=token, repo=repo))
            n += 1
        else:
            break

    # Fallback to single repo
    if not configs and settings.github_token and settings.github_target_repo:
        configs.append(
            GitHubRepoConfig(
                token=settings.github_token,
                repo=settings.github_target_repo,
            )
        )

    return configs
