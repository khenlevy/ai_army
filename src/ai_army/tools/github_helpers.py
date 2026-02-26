"""Shared helpers for GitHub API (repo resolution, README, issue count, connection check)."""

import logging

from github import Auth, Github

from ai_army.config.settings import get_github_repos, settings
from ai_army.config.settings import GitHubRepoConfig

logger = logging.getLogger(__name__)


def _get_repo_from_config(config: GitHubRepoConfig | None = None):
    """Get the target repository. Uses config if provided, else first repo from settings."""
    if config:
        auth = Auth.Token(config.token)
        client = Github(auth=auth)
        return client.get_repo(config.repo)
    repos = get_github_repos()
    if not repos:
        if settings.github_target_token and settings.github_target_repo:
            auth = Auth.Token(settings.github_target_token)
            client = Github(auth=auth)
            return client.get_repo(settings.github_target_repo)
        logger.error("No GitHub repo configured. Set GITHUB_TARGET_REPO and GITHUB_TARGET_TOKEN or GITHUB_REPO_1 and GITHUB_TOKEN_1.")
        raise ValueError(
            "No GitHub repo configured. Set GITHUB_TARGET_REPO and GITHUB_TARGET_TOKEN or GITHUB_REPO_1 and GITHUB_TOKEN_1."
        )
    c = repos[0]
    auth = Auth.Token(c.token)
    client = Github(auth=auth)
    return client.get_repo(c.repo)


def get_repo_from_config(config: GitHubRepoConfig | None = None):
    """Public: get the GitHub repository for the given config (or default)."""
    return _get_repo_from_config(config)


def get_open_issue_count(repo) -> int:
    """Count open issues only (exclude pull requests)."""
    issues = list(repo.get_issues(state="open"))
    return sum(1 for i in issues if not i.pull_request)


def get_repo_readme(repo) -> str:
    """Fetch README content from the repo. Returns empty string if missing or on error."""
    try:
        readme = repo.get_readme()
        return readme.decoded_content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("get_repo_readme: could not fetch README: %s", e)
        return ""


def count_issues_ready_for_breakdown(repo_config: GitHubRepoConfig | None = None) -> int:
    """Count open issues with ready-for-breakdown that do NOT have broken-down. GitHub API only."""
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=["ready-for-breakdown"]))
        count = 0
        for i in issues:
            if i.pull_request:
                continue
            label_names = {l.name for l in (i.labels or [])}
            if "broken-down" not in label_names:
                count += 1
        return count
    except Exception as e:
        logger.warning("count_issues_ready_for_breakdown failed: %s", e)
        return 0


def count_issues_for_dev(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> int:
    """Count open issues with agent_type label that do NOT have in-progress or in-review. GitHub API only."""
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=[agent_type]))
        count = 0
        for i in issues:
            if i.pull_request:
                continue
            label_names = {l.name for l in (i.labels or [])}
            if "in-progress" in label_names or "in-review" in label_names:
                continue
            count += 1
        return count
    except Exception as e:
        logger.warning("count_issues_for_dev(%s) failed: %s", agent_type, e)
        return 0


def check_github_connection_and_log(
    repos: list[GitHubRepoConfig] | None = None,
) -> list[tuple[GitHubRepoConfig, bool]]:
    """Verify we can connect to GitHub and access each configured repo. Log results.

    Returns list of (repo_config, success). Call at startup or before jobs to confirm connectivity.
    """
    if repos is None:
        repos = get_github_repos()
    results: list[tuple[GitHubRepoConfig, bool]] = []
    for cfg in repos:
        try:
            client = Github(auth=Auth.Token(cfg.token))
            repo = client.get_repo(cfg.repo)
            _ = repo.full_name
            logger.info("GitHub connected | repo: %s", cfg.repo)
            results.append((cfg, True))
        except Exception as e:
            logger.warning("GitHub connection failed | repo: %s | %s", cfg.repo, e)
            results.append((cfg, False))
    return results
