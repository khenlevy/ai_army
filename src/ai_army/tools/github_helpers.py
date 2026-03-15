"""Shared helpers for GitHub API (repo resolution, README, issue count, connection check)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import yaml
from github import Auth, Github

from ai_army.config.settings import get_github_repos, settings
from ai_army.config.settings import GitHubRepoConfig

logger = logging.getLogger(__name__)

DEV_REVIEW_LABELS = {"in-review", "awaiting-review", "awaiting-merge"}


@dataclass
class IssueExecutionMeta:
    """Parsed execution metadata embedded in a sub-issue body."""

    file_scope: list[str] = field(default_factory=list)
    depends_on: int | None = None
    priority: int = 100


@dataclass
class DevIssueCandidate:
    """A dev issue plus the metadata needed for scheduling decisions."""

    issue_number: int
    title: str
    is_in_progress: bool
    priority: int = 100
    depends_on: int | None = None
    file_scope: list[str] = field(default_factory=list)
    linked_pr_number: int | None = None
    linked_pr_branch: str = ""
    linked_pr_mergeable: bool | None = None


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


def _issue_meta_block(issue_body: str | None) -> str:
    """Return the embedded ai-army metadata block, if present."""
    if not issue_body:
        return ""
    match = re.search(r"<!--\s*ai-army-meta\s*(.*?)-->", issue_body, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_issue_execution_meta(issue_body: str | None) -> IssueExecutionMeta:
    """Parse dependency and file-scope metadata from an issue body."""
    raw = _issue_meta_block(issue_body)
    if not raw:
        return IssueExecutionMeta()
    try:
        payload = yaml.safe_load(raw) or {}
    except Exception as exc:
        logger.warning("parse_issue_execution_meta failed: %s", exc)
        return IssueExecutionMeta()
    if not isinstance(payload, dict):
        return IssueExecutionMeta()
    file_scope = payload.get("file_scope") or []
    if isinstance(file_scope, str):
        file_scope = [file_scope]
    depends_on = payload.get("depends_on")
    if isinstance(depends_on, str):
        match = re.search(r"#?(\d+)", depends_on)
        depends_on = int(match.group(1)) if match else None
    priority = payload.get("priority", 100)
    try:
        priority_value = int(priority)
    except (TypeError, ValueError):
        priority_value = 100
    return IssueExecutionMeta(
        file_scope=[str(item) for item in file_scope if str(item).strip()],
        depends_on=depends_on if isinstance(depends_on, int) else None,
        priority=priority_value,
    )


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


def count_prioritized_needing_enrichment(repo_config: GitHubRepoConfig | None = None) -> int:
    """Count open issues with 'prioritized' but NOT 'ready-for-breakdown'. GitHub API only."""
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=["prioritized"]))
        count = 0
        for i in issues:
            if i.pull_request:
                continue
            label_names = {l.name for l in (i.labels or [])}
            if "ready-for-breakdown" not in label_names:
                count += 1
        return count
    except Exception as e:
        logger.warning("count_prioritized_needing_enrichment failed: %s", e)
        return 0


def _issue_linked_in_pr_body(pr_body: str | None, issue_number: int) -> bool:
    """Check if PR body contains a GitHub-closing reference for the given issue."""
    if not pr_body:
        return False
    pattern = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*(?:[\w.-]+/[\w.-]+)?#(\d+)"
    for match in re.finditer(pattern, pr_body, re.IGNORECASE):
        if int(match.group(1)) == issue_number:
            return True
    return False


def _refresh_mergeable(repo, pr_number: int, attempts: int = 3, delay_seconds: float = 0.5) -> bool | None:
    """Fetch mergeable status, retrying when GitHub has not computed it yet."""
    mergeable: bool | None = None
    for _ in range(attempts):
        pr = repo.get_pull(pr_number)
        mergeable = pr.mergeable
        if mergeable is not None:
            return mergeable
        time.sleep(delay_seconds)
    return mergeable


def find_linked_open_pr(repo, issue_number: int):
    """Return the first open PR that links to the issue via Closes/Fixes."""
    try:
        for pr in repo.get_pulls(state="open"):
            if _issue_linked_in_pr_body(pr.body, issue_number):
                return pr
    except Exception as e:
        logger.warning("find_linked_open_pr(%s) failed: %s", issue_number, e)
    return None


def issue_has_open_pr(repo, issue_number: int) -> bool:
    """Check if any open PR references this issue via Closes #N or Fixes #N."""
    return find_linked_open_pr(repo, issue_number) is not None


def dependency_is_satisfied(repo, dependency_issue_number: int | None) -> bool:
    """Return True when the dependent issue has already landed."""
    if not dependency_issue_number:
        return True
    try:
        dependency = repo.get_issue(dependency_issue_number)
    except Exception as exc:
        logger.warning("dependency_is_satisfied(%s) failed to fetch issue: %s", dependency_issue_number, exc)
        return False
    if dependency.state.lower() == "closed":
        return True
    labels = {label.name for label in (dependency.labels or [])}
    return "done" in labels


def list_dev_issue_candidates(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> list[DevIssueCandidate]:
    """Return dev candidates enriched with dependency and PR metadata."""
    try:
        repo = _get_repo_from_config(repo_config)
        issues = list(repo.get_issues(state="open", labels=[agent_type]))
        candidates: list[DevIssueCandidate] = []
        for issue in issues:
            if issue.pull_request:
                continue
            labels = {label.name for label in (issue.labels or [])}
            meta = parse_issue_execution_meta(issue.body or "")
            linked_pr = find_linked_open_pr(repo, issue.number)
            mergeable = _refresh_mergeable(repo, linked_pr.number) if linked_pr else None
            candidates.append(
                DevIssueCandidate(
                    issue_number=issue.number,
                    title=issue.title or "",
                    is_in_progress="in-progress" in labels,
                    priority=meta.priority,
                    depends_on=meta.depends_on,
                    file_scope=meta.file_scope,
                    linked_pr_number=linked_pr.number if linked_pr else None,
                    linked_pr_branch=linked_pr.head.ref if linked_pr else "",
                    linked_pr_mergeable=mergeable,
                )
            )
        candidates.sort(key=lambda candidate: (candidate.priority, candidate.issue_number))
        return candidates
    except Exception as e:
        logger.warning("list_dev_issue_candidates(%s) failed: %s", agent_type, e)
        return []


def count_issues_for_dev(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> int:
    """Count open issues with agent_type label that Dev can work on.

    Includes: (a) fresh issues (no in-progress/in-review/awaiting-*), (b) in-progress
    issues with no open PR yet (continue existing work).
    Excludes: in-review, awaiting-review, awaiting-merge (PR exists).
    """
    return len(list_issues_for_dev(repo_config, agent_type))


def list_issues_for_dev(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> list[tuple[int, str, bool]]:
    """List issues Dev can work on: (issue_number, title, is_in_progress).

    Same inclusion logic as count_issues_for_dev. Used for pre-run branch context.
    """
    result: list[tuple[int, str, bool]] = []
    try:
        repo = _get_repo_from_config(repo_config)
        for candidate in list_dev_issue_candidates(repo_config, agent_type):
            issue = repo.get_issue(candidate.issue_number)
            labels = {label.name for label in (issue.labels or [])}
            if DEV_REVIEW_LABELS & labels:
                continue
            if not dependency_is_satisfied(repo, candidate.depends_on):
                continue
            if candidate.is_in_progress and candidate.linked_pr_number:
                continue
            result.append((candidate.issue_number, candidate.title, candidate.is_in_progress))
        return result
    except Exception as e:
        logger.warning("list_issues_for_dev(%s) failed: %s", agent_type, e)
        return []


def find_conflicting_agent_prs(
    repo_config: GitHubRepoConfig | None = None,
    agent_type: str = "frontend",
) -> list[dict[str, Any]]:
    """Find open PRs for the agent type that currently have merge conflicts."""
    try:
        repo = _get_repo_from_config(repo_config)
        conflicts: list[dict[str, Any]] = []
        issues = list(repo.get_issues(state="open", labels=[agent_type]))
        for issue in issues:
            if issue.pull_request:
                continue
            labels = {label.name for label in (issue.labels or [])}
            if "in-progress" not in labels and not (DEV_REVIEW_LABELS & labels):
                continue
            pr = find_linked_open_pr(repo, issue.number)
            if not pr:
                continue
            mergeable = _refresh_mergeable(repo, pr.number)
            if mergeable is not False:
                continue
            conflicts.append(
                {
                    "pr_number": pr.number,
                    "branch_name": pr.head.ref,
                    "base_branch": pr.base.ref,
                    "issue_number": issue.number,
                    "issue_title": issue.title or "",
                }
            )
        return conflicts
    except Exception as exc:
        logger.warning("find_conflicting_agent_prs(%s) failed: %s", agent_type, exc)
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
