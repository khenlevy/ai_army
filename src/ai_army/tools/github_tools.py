"""CrewAI tools wrapping PyGithub for GitHub API integration.

All agents use these tools as the single integration layer for issues, PRs, and repo activity.
Supports multiple repos via repo_config. Implementation split across github_helpers,
github_issue_tools, and github_pr_tools to keep files under the line limit.
"""

from ai_army.config.settings import GitHubRepoConfig
from ai_army.tools.github_helpers import (
    check_github_connection_and_log,
    count_issues_for_dev,
    count_issues_ready_for_breakdown,
    get_open_issue_count,
    get_repo_from_config,
    get_repo_readme,
)
from ai_army.tools.github_issue_tools import (
    BreakdownAndCreateSubIssuesTool,
    CreateIssueTool,
    CreateStructuredIssueTool,
    EnrichIssueTool,
    ListOpenIssuesTool,
    UpdateIssueTool,
)
from ai_army.tools.github_pr_tools import (
    CreateBranchTool,
    CreatePullRequestTool,
    ListPullRequestsTool,
    MergePullRequestTool,
    ReviewPullRequestTool,
)


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


__all__ = [
    "check_github_connection_and_log",
    "get_open_issue_count",
    "get_repo_from_config",
    "get_repo_readme",
    "create_github_tools",
    "BreakdownAndCreateSubIssuesTool",
    "CreateIssueTool",
    "CreateStructuredIssueTool",
    "EnrichIssueTool",
    "UpdateIssueTool",
    "ListOpenIssuesTool",
    "CreatePullRequestTool",
    "ListPullRequestsTool",
    "MergePullRequestTool",
    "ReviewPullRequestTool",
    "CreateBranchTool",
]
