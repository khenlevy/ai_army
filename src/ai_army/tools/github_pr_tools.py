"""GitHub PR and branch tools. CrewAI tools wrapping PyGithub."""

import re
import logging
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.config.settings import GitHubRepoConfig
from ai_army.tools.github_helpers import _get_repo_from_config
from ai_army.tools.github_issue_tools import UpdateIssueTool

logger = logging.getLogger(__name__)


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
        try:
            repo = _get_repo_from_config(self._repo_config)
            pr = repo.create_pull(title=title, body=body, head=head, base=base)
            logger.info("CreatePullRequestTool: created PR #%s %s (%s -> %s)", pr.number, title, head, base)
            return f"Created PR #{pr.number}: {title} ({head} -> {base})"
        except Exception as e:
            logger.exception("CreatePullRequestTool failed: %s", e)
            raise


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
        logger.info("ListPullRequestsTool: found %d PRs (state=%s)", len(result), state)
        return "\n".join(result) if result else "No pull requests found"


class ReviewPullRequestInput(BaseModel):
    """Input schema for ReviewPullRequestTool."""

    pr_number: int = Field(..., description="Pull request number to review")


class ReviewPullRequestTool(BaseTool):
    """Review a PR with structured output and merge or request changes."""

    name: str = "Review Pull Request"
    description: str = (
        "Review a pull request. Produces a structured decision (merge or request_changes) "
        "with feedback points. Merges if approved, or adds feedback to the linked issue."
    )
    args_schema: Type[BaseModel] = ReviewPullRequestInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, pr_number: int) -> str:
        from ai_army.chains.qa_chains import review_pr_chain
        from ai_army.schemas.qa_schemas import ReviewSpec

        repo = _get_repo_from_config(self._repo_config)
        try:
            pr = repo.get_pull(pr_number)
            pr_title = pr.title
            pr_body = pr.body or ""
            files_list = list(pr.get_files())
            files_summary = "\n".join(f"- {f.filename}" for f in files_list[:30])
            if len(files_list) > 30:
                files_summary += "\n..."
        except Exception as e:
            logger.warning("ReviewPullRequestTool: could not fetch PR #%s: %s", pr_number, e)
            return f"Error fetching PR #{pr_number}: {e}"

        logger.info("ReviewPullRequestTool: fetching structured review for PR #%s", pr_number)
        prompt = f"""Review this pull request.

PR #{pr_number}: {pr_title}
Body: {pr_body}

Files changed:
{files_summary}

Decide: merge (if looks good) or request_changes (if feedback needed).
Provide feedback_points (file, line, comment) for any issues. Prefer merging when in doubt."""
        try:
            chain = review_pr_chain()
            spec: ReviewSpec = chain.invoke(prompt)
            logger.info("ReviewPullRequestTool: decision=%s for PR #%s", spec.decision, pr_number)
        except Exception as e:
            logger.exception("ReviewPullRequestTool chain failed: %s", e)
            return f"Error producing review: {e}"

        if spec.decision == "merge":
            merge_tool = MergePullRequestTool(repo_config=self._repo_config)
            result = merge_tool._run(pr_number=pr_number)
            issue_num = _extract_closes_issue(pr_body)
            if issue_num:
                update_tool = UpdateIssueTool(repo_config=self._repo_config)
                update_tool._run(issue_number=issue_num, labels_to_add=["done"])
                logger.info("ReviewPullRequestTool: merged PR #%s, set done on issue #%s", pr_number, issue_num)
                result += f" | Set 'done' on issue #{issue_num}"
            else:
                logger.info("ReviewPullRequestTool: merged PR #%s", pr_number)
            return result

        logger.info("ReviewPullRequestTool: request_changes for PR #%s, %d feedback points", pr_number, len(spec.feedback_points))
        comment_parts = [spec.summary] if spec.summary else []
        for fp in spec.feedback_points:
            loc = f"{fp.file}:L{fp.line}" if fp.line else fp.file or "general"
            comment_parts.append(f"- [{loc}] {fp.comment}")
        comment = "\n".join(comment_parts)
        issue_num = _extract_closes_issue(pr_body)
        if issue_num:
            update_tool = UpdateIssueTool(repo_config=self._repo_config)
            result = update_tool._run(
                issue_number=issue_num,
                comment=f"[QA Agent]\n\nPR #{pr_number} feedback:\n\n{comment}",
            )
            logger.info("ReviewPullRequestTool: added feedback to issue #%s for PR #%s", issue_num, pr_number)
            return result
        return f"Review: request_changes. Feedback: {comment}"


def _extract_closes_issue(body: str) -> int | None:
    """Extract issue number from Closes #N or Fixes #N in PR body."""
    if not body:
        return None
    match = re.search(r"(?:Closes|Fixes)\s*#(\d+)", body, re.IGNORECASE)
    return int(match.group(1)) if match else None


class MergePullRequestInput(BaseModel):
    """Input schema for MergePullRequestTool."""

    pr_number: int = Field(..., description="Pull request number to merge")
    merge_method: str = Field(default="merge", description="merge, squash, or rebase")
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
        logger.info("MergePullRequestTool: merged PR #%s using %s", pr_number, merge_method)
        return f"Merged PR #{pr_number} using {merge_method}"


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
        logger.info("CreateBranchTool: created branch '%s' from %s", branch_name, from_ref)
        return f"Created branch '{branch_name}' from {from_ref}"
