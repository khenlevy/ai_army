"""Pydantic settings for AI-Army configuration."""

import logging
import os
from dataclasses import dataclass
from typing import Iterator

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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

    # Anthropic Claude model for all crews and chains. ANTHROPIC_LLM_MODEL env.
    # claude-3-5-haiku-20241022 deprecated 2026-02-19. Use claude-haiku-4-5.
    anthropic_llm_model: str = "claude-haiku-4-5"

    # Single repo (backward compat)
    github_target_token: str = ""
    github_target_repo: str = ""

    # Multi-repo: GITHUB_REPO_1, GITHUB_TOKEN_1, GITHUB_REPO_2, GITHUB_TOKEN_2, ...
    # Loaded dynamically - see get_github_repos()

    # Local clone path for git operations (override when dev crew clones automatically).
    local_repo_path: str = ""

    # Directory where dev crew clones target repos (GITHUB_TARGET_REPO / GITHUB_REPO_N). Default: .ai_army_workspace in cwd.
    repo_workspace: str = ""

    # RAG embedding model for codebase search (dev agents). sentence-transformers model ID.
    rag_embedding_model: str = "all-MiniLM-L6-v2"


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


settings = get_settings()


def get_github_repos() -> list[GitHubRepoConfig]:
    """Get list of GitHub repo configs from env.

    Supports:
    - Single: GITHUB_TARGET_TOKEN, GITHUB_TARGET_REPO
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
    if not configs and settings.github_target_token and settings.github_target_repo:
        configs.append(
            GitHubRepoConfig(
                token=settings.github_target_token,
                repo=settings.github_target_repo,
            )
        )
        logger.debug("get_github_repos: using single repo config (GITHUB_TARGET_REPO)")
    elif configs:
        logger.debug("get_github_repos: loaded %d repo(s) from env", len(configs))
    else:
        logger.warning("get_github_repos: no repos configured")

    return configs
