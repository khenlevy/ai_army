"""CrewAI tools for local git operations (branch, commit, push).

Agents use these when working in a cloned repo configured via LOCAL_REPO_PATH.
"""

import subprocess
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.config.settings import settings


def _repo_path(override: str | None = None) -> Path | None:
    """Resolve the local repo path. Returns None if not configured."""
    path = override or settings.local_repo_path
    if not path or not path.strip():
        return None
    p = Path(path).expanduser().resolve()
    if not (p / ".git").exists():
        return None
    return p


def _run_git(repo_path: Path, *args: str) -> str:
    """Run a git command in repo_path. Returns combined stdout and stderr."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    combined = "\n".join(filter(None, [out, err]))
    if result.returncode != 0:
        return f"git exited {result.returncode}: {combined}"
    return combined or "ok"


# --- CreateLocalBranchTool ---


class CreateLocalBranchInput(BaseModel):
    """Input schema for CreateLocalBranchTool."""

    branch_name: str = Field(..., description="Name of the new branch")
    from_ref: str = Field(default="main", description="Branch or ref to create from (e.g. main)")


class CreateLocalBranchTool(BaseTool):
    """Create and checkout a new branch in the local clone."""

    name: str = "Create Local Branch"
    description: str = (
        "Create a new branch in the local repo and switch to it. Use before making changes. "
        "Branch name should match what you will use for the PR (e.g. feature/issue-5-add-button)."
    )
    args_schema: Type[BaseModel] = CreateLocalBranchInput

    def _run(self, branch_name: str, from_ref: str = "main") -> str:
        repo = _repo_path()
        if not repo:
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        out = _run_git(repo, "checkout", "-b", branch_name, from_ref)
        if "exited" in out:
            return out
        return f"Created and checked out branch '{branch_name}' from {from_ref}"


# --- GitCommitTool ---


class GitCommitInput(BaseModel):
    """Input schema for GitCommitTool."""

    message: str = Field(..., description="Commit message")
    paths: str = Field(
        default=".",
        description="Paths to add and commit: '.' for all changed files, or space-separated paths",
    )


class GitCommitTool(BaseTool):
    """Stage and commit changes in the local repo."""

    name: str = "Git Commit"
    description: str = (
        "Stage files and create a commit in the local repo. Use after editing files. "
        "Set paths to '.' to commit all changed files, or list specific paths."
    )
    args_schema: Type[BaseModel] = GitCommitInput

    def _run(self, message: str, paths: str = ".") -> str:
        repo = _repo_path()
        if not repo:
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        add_args = paths.split() if paths.strip() != "." else ["."]
        _run_git(repo, "add", *add_args)
        out = _run_git(repo, "commit", "-m", message)
        if "exited" in out:
            return out
        return f"Committed: {message}"


# --- GitPushTool ---


class GitPushInput(BaseModel):
    """Input schema for GitPushTool."""

    branch: str = Field(
        default="",
        description="Branch to push (default: current branch). Use the same name as Create Local Branch.",
    )
    remote: str = Field(default="origin", description="Remote name (default: origin)")


class GitPushTool(BaseTool):
    """Push the current (or given) branch to the remote."""

    name: str = "Git Push"
    description: str = (
        "Push the branch to the remote so a PR can be opened. Use after committing. "
        "Leave branch empty to push the current branch."
    )
    args_schema: Type[BaseModel] = GitPushInput

    def _run(self, branch: str = "", remote: str = "origin") -> str:
        repo = _repo_path()
        if not repo:
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        if branch.strip():
            refspec = branch
        else:
            out = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            if "exited" in out:
                return out
            refspec = out.strip()
        out = _run_git(repo, "push", remote, refspec)
        if "exited" in out:
            return out
        return f"Pushed {refspec} to {remote}"
