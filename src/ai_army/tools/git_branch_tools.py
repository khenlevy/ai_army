"""CrewAI tools for git branch introspection and checkout.

Used by Dev agents to see what's done on a branch and to checkout existing branches when continuing work.
"""

import logging
import re
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.tools.git_tools import _repo_path, _run_git

logger = logging.getLogger(__name__)

DEFAULT_BASE = "main"


def _run_git_in(repo_path: Path, *args: str) -> str:
    """Run git in repo_path; return output or error string."""
    return _run_git(repo_path, *args)


def _infer_issue_from_branch(branch_name: str) -> int | None:
    """Parse feature/issue-N-* pattern to infer issue number."""
    match = re.search(r"issue-(\d+)(?:-|$)", branch_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


class GitBranchStatusInput(BaseModel):
    """Input schema for GitBranchStatusTool."""

    branch_name: str = Field(
        default="",
        description="Branch to inspect. Leave empty for current branch.",
    )
    base_ref: str = Field(
        default="main",
        description="Base ref to compare against (main or origin/main)",
    )


class GitBranchStatusTool(BaseTool):
    """Show branch status: commits ahead of base, files changed, and inferred issue number.

    Use when continuing in-progress work to see what's already done on a branch.
    """

    name: str = "Git Branch Status"
    description: str = (
        "Show status of a branch: commits ahead of main, files changed, and inferred issue number from branch name. "
        "Use when continuing existing work to see what was already implemented."
    )
    args_schema: Type[BaseModel] = GitBranchStatusInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, branch_name: str = "", base_ref: str = DEFAULT_BASE) -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitBranchStatusTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."

        if not branch_name.strip():
            out = _run_git_in(repo, "rev-parse", "--abbrev-ref", "HEAD")
            if "exited" in out:
                return out
            branch_name = out.strip()

        # Check if branch exists (local or remote)
        branches_out = _run_git_in(repo, "branch", "-a")
        if "exited" in branches_out:
            return branches_out
        branch_exists = branch_name in branches_out or f"remotes/origin/{branch_name}" in branches_out
        if not branch_exists:
            return f"Branch '{branch_name}' not found (local or remote)."

        # Resolve base ref - try origin/main if main not local
        base = base_ref
        if base == "main":
            check_main = _run_git_in(repo, "rev-parse", "--verify", "main")
            if "exited" in check_main:
                base = "origin/main"

        log_out = _run_git_in(repo, "log", f"{base}..{branch_name}", "--oneline")
        if "exited" in log_out:
            return log_out

        diff_out = _run_git_in(repo, "diff", f"{base}..{branch_name}", "--stat")
        if "exited" in diff_out:
            diff_out = "(diff failed)"

        # Check if on remote
        remote_out = _run_git_in(repo, "branch", "-r")
        on_remote = "exited" not in remote_out and f"origin/{branch_name}" in remote_out

        lines = []
        issue_num = _infer_issue_from_branch(branch_name)
        header = f"Branch {branch_name}"
        if issue_num:
            header += f" (likely issue #{issue_num})"
        lines.append(header + ":")

        commit_lines = [l.strip() for l in log_out.splitlines() if l.strip()]
        lines.append(f"  Commits ahead of {base}: {len(commit_lines)}")
        for c in commit_lines[:10]:
            lines.append(f"  - {c}")
        if len(commit_lines) > 10:
            lines.append(f"  ... and {len(commit_lines) - 10} more")

        if diff_out and diff_out.strip():
            files = [l.split("|")[0].strip() for l in diff_out.splitlines() if "|" in l]
            if files:
                lines.append("  Files changed: " + ", ".join(files[:8]))
                if len(files) > 8:
                    lines.append(f"    ... and {len(files) - 8} more")

        lines.append(f"  On remote: {'yes' if on_remote else 'no'}")

        logger.info("GitBranchStatusTool: reported status for %s", branch_name)
        return "\n".join(lines)


class CheckoutBranchInput(BaseModel):
    """Input schema for CheckoutBranchTool."""

    branch_name: str = Field(..., description="Name of the branch to checkout")


class CheckoutBranchTool(BaseTool):
    """Checkout an existing branch in the local clone.

    Use when continuing in-progress work: checkout the existing branch instead of creating a new one.
    """

    name: str = "Checkout Branch"
    description: str = (
        "Checkout an existing branch. Use when continuing in-progress work—the branch already exists. "
        "Do NOT use Create Local Branch for existing branches; use this tool instead."
    )
    args_schema: Type[BaseModel] = CheckoutBranchInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, branch_name: str) -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("CheckoutBranchTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."

        out = _run_git_in(repo, "checkout", branch_name)
        if "exited" in out:
            return out
        logger.info("CheckoutBranchTool: checked out branch '%s'", branch_name)
        return f"Checked out branch '{branch_name}'"
