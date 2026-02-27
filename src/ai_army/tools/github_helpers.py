"""Shared helpers for GitHub API (repo resolution, README, issue count, connection check)."""

import logging
import re

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


def _issue_linked_in_pr_body(pr_body: str | None, issue_number: int) -> bool:
    """Check if PR body contains Closes #N or Fixes #N for the given issue."""
    if not pr_body:
        return False
    for match in re.finditer(r"(?:Closes|Fixes)\s*#(\d+)", pr_body, re.IGNORECASE):
        if int(match.group(1)) == issue_number:
            return True
    return False


def issue_has_open_pr(repo, issue_number: int) -> bool:
    """Check if any open PR references this issue via Closes #N or Fixes #N."""
    try:
        for pr in repo.get_pulls(state="open"):
            if _issue_linked_in_pr_body(pr.body, issue_number):
                return True
        return False
    except Exception as e:
        logger.warning("issue_has_open_pr(%s) failed: %s", issue_number, e)
        return False


def count_issues_for_dev(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> int:
    """Count open issues with agent_type label that Dev can work on.

    Includes: (a) fresh issues (no in-progress/in-review/awaiting-*), (b) in-progress
    issues with no open PR yet (continue existing work).
    Excludes: in-review, awaiting-review, awaiting-merge (PR exists).
    """
    skip_labels = {"in-review", "awaiting-review", "awaiting-merge"}
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=[agent_type]))
        count = 0
        for i in issues:
            if i.pull_request:
                continue
            label_names = {l.name for l in (i.labels or [])}
            if skip_labels & label_names:
                continue
            if "in-progress" in label_names:
                if issue_has_open_pr(repo, i.number):
                    continue
            count += 1
        return count
    except Exception as e:
        logger.warning("count_issues_for_dev(%s) failed: %s", agent_type, e)
        return 0


def list_issues_for_dev(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> list[tuple[int, str, bool]]:
    """List issues Dev can work on: (issue_number, title, is_in_progress).

    Same inclusion logic as count_issues_for_dev. Used for pre-run branch context.
    """
    skip_labels = {"in-review", "awaiting-review", "awaiting-merge"}
    result: list[tuple[int, str, bool]] = []
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=[agent_type]))
        for i in issues:
            if i.pull_request:
                continue
            label_names = {l.name for l in (i.labels or [])}
            if skip_labels & label_names:
                continue
            if "in-progress" in label_names:
                if issue_has_open_pr(repo, i.number):
                    continue
                result.append((i.number, i.title or "", True))
            else:
                result.append((i.number, i.title or "", False))
        return result
    except Exception as e:
        logger.warning("list_issues_for_dev(%s) failed: %s", agent_type, e)
        return []


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
