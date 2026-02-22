"""CrewAI tools wrapping PyGithub for GitHub API integration.

All agents use these tools as the single integration layer for issues, PRs, and repo activity.
Supports multiple repos via repo_config.
"""

import logging
from typing import Type

from crewai.tools import BaseTool
from github import Auth, Github
from pydantic import BaseModel, Field

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
        auth = Auth.Token(settings.github_token)
        client = Github(auth=auth)
        return client.get_repo(settings.github_target_repo)
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
    except Exception:
        return ""


def check_github_connection_and_log(repos: list[GitHubRepoConfig] | None = None) -> list[tuple[GitHubRepoConfig, bool]]:
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
            # Light touch to confirm access (e.g. repo full_name)
            _ = repo.full_name
            logger.info("GitHub connected | repo: %s", cfg.repo)
            results.append((cfg, True))
        except Exception as e:
            logger.warning("GitHub connection failed | repo: %s | %s", cfg.repo, e)
            results.append((cfg, False))
    return results


# --- CreateIssueTool ---


class CreateIssueInput(BaseModel):
    """Input schema for CreateIssueTool."""

    title: str = Field(..., description="Issue title")
    body: str = Field(default="", description="Issue body/description")
    labels: list[str] = Field(default_factory=list, description="Labels to apply (e.g. backlog, feature)")


class CreateIssueTool(BaseTool):
    """Create a GitHub issue with title, body, and labels."""

    name: str = "Create GitHub Issue"
    description: str = (
        "Create a new GitHub issue in the target repository. Use for backlog items, features, or bugs. "
        "Apply lifecycle labels like 'backlog', 'prioritized', 'feature', or 'bug'."
    )
    args_schema: Type[BaseModel] = CreateIssueInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, title: str, body: str = "", labels: list[str] | None = None) -> str:
        labels = labels or []
        repo = _get_repo_from_config(self._repo_config)
        issue = repo.create_issue(title=title, body=body, labels=labels)
        return f"Created issue #{issue.number}: {title} (labels: {labels})"


# --- UpdateIssueTool ---


class UpdateIssueInput(BaseModel):
    """Input schema for UpdateIssueTool."""

    issue_number: int = Field(..., description="Issue number to update")
    comment: str = Field(default="", description="Add a comment to the issue")
    labels_to_add: list[str] = Field(default_factory=list, description="Labels to add")
    labels_to_remove: list[str] = Field(default_factory=list, description="Labels to remove")
    assignee: str = Field(default="", description="Username to assign (empty to skip)")


class UpdateIssueTool(BaseTool):
    """Add comments, update labels, or assign an issue."""

    name: str = "Update GitHub Issue"
    description: str = (
        "Update an existing GitHub issue: add comments, add/remove labels (e.g. in-progress, in-review, done), "
        "or assign to a user. Use lifecycle labels to track progress."
    )
    args_schema: Type[BaseModel] = UpdateIssueInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(
        self,
        issue_number: int,
        comment: str = "",
        labels_to_add: list[str] | None = None,
        labels_to_remove: list[str] | None = None,
        assignee: str = "",
    ) -> str:
        labels_to_add = labels_to_add or []
        labels_to_remove = labels_to_remove or []
        repo = _get_repo_from_config(self._repo_config)
        issue = repo.get_issue(issue_number)
        actions = []
        if comment:
            issue.create_comment(comment)
            actions.append("added comment")
        for label in labels_to_add:
            issue.add_to_labels(label)
            actions.append(f"added label '{label}'")
        for label in labels_to_remove:
            issue.remove_from_labels(label)
            actions.append(f"removed label '{label}'")
        if assignee:
            issue.add_to_assignees(assignee)
            actions.append(f"assigned to {assignee}")
        return f"Updated issue #{issue_number}: {', '.join(actions) or 'no changes'}" if actions else "No updates applied"


# --- ListOpenIssuesTool ---


class ListOpenIssuesInput(BaseModel):
    """Input schema for ListOpenIssuesTool."""

    labels: list[str] = Field(
        default_factory=list,
        description="Filter by labels (e.g. ready-for-breakdown, frontend). Empty = all open issues.",
    )
    limit: int = Field(default=50, ge=1, le=100, description="Max number of issues to return")


class ListOpenIssuesTool(BaseTool):
    """Fetch open issues for backlog/priorities, optionally filtered by labels."""

    name: str = "List Open GitHub Issues"
    description: str = (
        "List open GitHub issues in the target repository. Filter by labels (e.g. backlog, prioritized, "
        "ready-for-breakdown, frontend, backend, fullstack) to find issues for each workflow stage."
    )
    args_schema: Type[BaseModel] = ListOpenIssuesInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, labels: list[str] | None = None, limit: int = 50) -> str:
        labels = labels or []
        repo = _get_repo_from_config(self._repo_config)
        if labels:
            issues = list(repo.get_issues(state="open", labels=labels)[:limit])
        else:
            issues = list(repo.get_issues(state="open")[:limit])
        result = []
        for i in issues:
            if i.pull_request:
                continue  # Skip PRs, they appear in issues
            label_names = [l.name for l in i.labels]
            result.append(f"#{i.number}: {i.title} | labels: {label_names}")
        return "\n".join(result) if result else "No matching open issues found"


# --- CreatePullRequestTool ---


class CreatePullRequestInput(BaseModel):
    """Input schema for CreatePullRequestTool."""

    title: str = Field(..., description="PR title")
    body: str = Field(default="", description="PR description")
    head: str = Field(..., description="Branch name (source branch)")
    base: str = Field(default="main", description="Base branch to merge into")
    issue_number: int = Field(default=0, description="Related issue number for linking (e.g. Closes #123)")


class CreatePullRequestTool(BaseTool):
    """Create a pull request from a branch."""

    name: str = "Create Pull Request"
    description: str = (
        "Create a pull request from a branch. Include 'Closes #N' in body to link and auto-close the issue."
    )
    args_schema: Type[BaseModel] = CreatePullRequestInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(
        self,
        title: str,
        head: str,
        body: str = "",
        base: str = "main",
        issue_number: int = 0,
    ) -> str:
        if issue_number and "Closes #" not in body and "Fixes #" not in body:
            body = f"{body}\n\nCloses #{issue_number}".strip() if body else f"Closes #{issue_number}"
        repo = _get_repo_from_config(self._repo_config)
        pr = repo.create_pull(title=title, body=body, head=head, base=base)
        return f"Created PR #{pr.number}: {title} ({head} -> {base})"


# --- ListPullRequestsTool ---


class ListPullRequestsInput(BaseModel):
    """Input schema for ListPullRequestsTool."""

    state: str = Field(default="open", description="open, closed, or all")
    limit: int = Field(default=20, ge=1, le=100, description="Max number of PRs to return")


class ListPullRequestsTool(BaseTool):
    """List open pull requests for QA review."""

    name: str = "List Pull Requests"
    description: str = "List pull requests in the target repository. Use for QA to find PRs to review and merge."
    args_schema: Type[BaseModel] = ListPullRequestsInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, state: str = "open", limit: int = 20) -> str:
        repo = _get_repo_from_config(self._repo_config)
        prs = list(repo.get_pulls(state=state)[:limit])
        result = []
        for pr in prs:
            result.append(f"#{pr.number}: {pr.title} | {pr.head.ref} -> {pr.base.ref} | {pr.user.login}")
        return "\n".join(result) if result else "No pull requests found"


# --- MergePullRequestTool ---


class MergePullRequestInput(BaseModel):
    """Input schema for MergePullRequestTool."""

    pr_number: int = Field(..., description="Pull request number to merge")
    merge_method: str = Field(
        default="merge",
        description="merge, squash, or rebase",
    )
    commit_message: str = Field(default="", description="Optional commit message for merge")


class MergePullRequestTool(BaseTool):
    """Merge a pull request after QA approval."""

    name: str = "Merge Pull Request"
    description: str = "Merge a pull request. Use after QA review passes. Supports merge, squash, or rebase."
    args_schema: Type[BaseModel] = MergePullRequestInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(
        self,
        pr_number: int,
        merge_method: str = "merge",
        commit_message: str = "",
    ) -> str:
        repo = _get_repo_from_config(self._repo_config)
        pr = repo.get_pull(pr_number)
        pr.merge(merge_method=merge_method, commit_message=commit_message or None)
        return f"Merged PR #{pr_number} using {merge_method}"


# --- CreateBranchTool ---


class CreateBranchInput(BaseModel):
    """Input schema for CreateBranchTool."""

    branch_name: str = Field(..., description="Name of the new branch")
    from_ref: str = Field(default="main", description="Branch or ref to create from (e.g. main)")


class CreateBranchTool(BaseTool):
    """Create a new branch for development."""

    name: str = "Create Branch"
    description: str = "Create a new branch from main (or another ref) for development work."
    args_schema: Type[BaseModel] = CreateBranchInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, branch_name: str, from_ref: str = "main") -> str:
        repo = _get_repo_from_config(self._repo_config)
        branch = repo.get_branch(from_ref)
        sha = branch.commit.sha
        ref = repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        return f"Created branch '{branch_name}' from {from_ref}"


def create_github_tools(repo_config: GitHubRepoConfig | None = None) -> tuple:
    """Create GitHub tools bound to a specific repo config."""
    return (
        CreateIssueTool(repo_config=repo_config),
        UpdateIssueTool(repo_config=repo_config),
        ListOpenIssuesTool(repo_config=repo_config),
        CreatePullRequestTool(repo_config=repo_config),
        ListPullRequestsTool(repo_config=repo_config),
        MergePullRequestTool(repo_config=repo_config),
        CreateBranchTool(repo_config=repo_config),
    )
