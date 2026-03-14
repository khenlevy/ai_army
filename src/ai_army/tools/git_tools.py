"""CrewAI tools for local git operations (branch, commit, push).

Agents use these when working in a cloned repo configured via LOCAL_REPO_PATH.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.config.settings import settings

logger = logging.getLogger(__name__)


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
        logger.warning("git %s failed (exit %s): %s", " ".join(args[:3]), result.returncode, combined[:200])
        return f"git exited {result.returncode}: {combined}"
    return combined or "ok"


def _run_git_result(repo_path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run git and return the raw subprocess result."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    """Return combined stdout/stderr from a completed process."""
    return "\n".join(
        filter(None, [(result.stdout or "").strip(), (result.stderr or "").strip()])
    ) or "ok"


def _conflicting_files(repo_path: Path) -> list[str]:
    """Return files with unresolved merge conflicts, if any."""
    result = _run_git_result(repo_path, "diff", "--name-only", "--diff-filter=U")
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _slugify_agent_identity(value: str) -> str:
    """Convert a role/name into a stable local-part for git identity."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "agent"


def build_agent_identity(agent_name: str) -> tuple[str, str]:
    """Return git name and email for the given agent."""
    git_name = _slugify_agent_identity(agent_name)
    return git_name, f"{git_name}@{settings.agent_identity_domain}"


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

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, branch_name: str, from_ref: str = "main") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("CreateLocalBranchTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        out = _run_git(repo, "checkout", "-b", branch_name, from_ref)
        if "exited" in out:
            return out
        logger.info("CreateLocalBranchTool: created and checked out branch '%s' from %s", branch_name, from_ref)
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

    def __init__(
        self,
        repo_path: str | None = None,
        agent_name: str = "agent",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path
        self._agent_name = agent_name

    def _run(self, message: str, paths: str = ".") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitCommitTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        add_args = paths.split() if paths.strip() != "." else ["."]
        _run_git(repo, "add", *add_args)
        git_name, git_email = build_agent_identity(self._agent_name)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": git_name,
            "GIT_AUTHOR_EMAIL": git_email,
            "GIT_COMMITTER_NAME": git_name,
            "GIT_COMMITTER_EMAIL": git_email,
        }
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        out = _combined_output(result)
        if result.returncode != 0:
            logger.warning("git commit -m %s failed (exit %s): %s", message[:80], result.returncode, out[:200])
            return f"git exited {result.returncode}: {out}"
        if "exited" in out:
            return out
        logger.info("GitCommitTool: committed as %s <%s>: %s", git_name, git_email, message[:80])
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

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, branch: str = "", remote: str = "origin") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitPushTool: local repo not configured")
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
        logger.info("GitPushTool: pushed %s to %s", refspec, remote)
        return f"Pushed {refspec} to {remote}"


class GitRebaseInput(BaseModel):
    """Input schema for GitRebaseTool."""

    base_ref: str = Field(default="main", description="Base branch or ref to rebase onto")


class GitRebaseTool(BaseTool):
    """Rebase the current branch onto a base ref."""

    name: str = "Git Rebase"
    description: str = (
        "Rebase the current branch onto a base ref such as main. "
        "If conflicts occur, inspect the reported files, resolve them, then use Git Rebase Continue."
    )
    args_schema: Type[BaseModel] = GitRebaseInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, base_ref: str = "main") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitRebaseTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        result = _run_git_result(repo, "rebase", base_ref)
        output = _combined_output(result)
        if result.returncode == 0:
            logger.info("GitRebaseTool: rebased onto %s", base_ref)
            return f"Rebase completed successfully. Branch is now up to date with {base_ref}."
        files = _conflicting_files(repo)
        if files:
            logger.warning("GitRebaseTool: conflicts while rebasing onto %s: %s", base_ref, ", ".join(files))
            return (
                f"Rebase stopped due to conflicts in: {', '.join(files)}. "
                "Resolve conflicts, then use Git Rebase Continue."
            )
        return f"git exited {result.returncode}: {output}"


class GitRebaseContinueInput(BaseModel):
    """Input schema for GitRebaseContinueTool."""

    resolved_files: str = Field(
        default=".",
        description="Files already resolved. Use '.' to stage everything before continuing the rebase.",
    )


class GitRebaseContinueTool(BaseTool):
    """Stage resolved files and continue an in-progress rebase."""

    name: str = "Git Rebase Continue"
    description: str = (
        "Stage resolved files and continue an in-progress rebase. "
        "Use after removing conflict markers from files."
    )
    args_schema: Type[BaseModel] = GitRebaseContinueInput

    def __init__(self, repo_path: str | None = None, agent_name: str = "agent", **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path
        self._agent_name = agent_name

    def _run(self, resolved_files: str = ".") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitRebaseContinueTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        add_args = resolved_files.split() if resolved_files.strip() != "." else ["."]
        add_output = _run_git(repo, "add", *add_args)
        if "exited" in add_output:
            return add_output
        git_name, git_email = build_agent_identity(self._agent_name)
        result = _run_git_result(
            repo,
            "rebase",
            "--continue",
            env={
                **os.environ,
                "GIT_EDITOR": "true",
                "GIT_AUTHOR_NAME": git_name,
                "GIT_AUTHOR_EMAIL": git_email,
                "GIT_COMMITTER_NAME": git_name,
                "GIT_COMMITTER_EMAIL": git_email,
            },
        )
        output = _combined_output(result)
        if result.returncode == 0:
            logger.info("GitRebaseContinueTool: continued rebase successfully")
            return "Rebase continued successfully."
        files = _conflicting_files(repo)
        if files:
            return (
                f"Rebase still has conflicts in: {', '.join(files)}. "
                "Resolve the remaining files and run Git Rebase Continue again."
            )
        return f"git exited {result.returncode}: {output}"


class GitRebaseAbortInput(BaseModel):
    """Input schema for GitRebaseAbortTool."""


class GitRebaseAbortTool(BaseTool):
    """Abort an in-progress rebase."""

    name: str = "Git Rebase Abort"
    description: str = "Abort the current rebase and return the branch to its pre-rebase state."
    args_schema: Type[BaseModel] = GitRebaseAbortInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self) -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitRebaseAbortTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        output = _run_git(repo, "rebase", "--abort")
        if "exited" in output:
            return output
        logger.info("GitRebaseAbortTool: aborted rebase")
        return "Rebase aborted."


class GitForcePushInput(BaseModel):
    """Input schema for GitForcePushTool."""

    branch: str = Field(
        default="",
        description="Branch to push with --force-with-lease (default: current branch).",
    )
    remote: str = Field(default="origin", description="Remote name (default: origin)")


class GitForcePushTool(BaseTool):
    """Force-push the current branch after a rebase."""

    name: str = "Git Force Push"
    description: str = (
        "Push the current branch with --force-with-lease after rebasing or rewriting history. "
        "Use only to update an existing PR branch."
    )
    args_schema: Type[BaseModel] = GitForcePushInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path_override = repo_path

    def _run(self, branch: str = "", remote: str = "origin") -> str:
        repo = _repo_path(self._repo_path_override)
        if not repo:
            logger.warning("GitForcePushTool: local repo not configured")
            return "Local repo not configured. Set LOCAL_REPO_PATH to the path of your cloned repo."
        refspec = branch.strip()
        if not refspec:
            out = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            if "exited" in out:
                return out
            refspec = out.strip()
        if refspec in {"main", "master"}:
            logger.warning("GitForcePushTool: refusing to force-push protected branch %s", refspec)
            return f"Refusing to force-push protected branch '{refspec}'. Provide the PR branch explicitly."
        out = _run_git(repo, "push", "--force-with-lease", remote, refspec)
        if "exited" in out:
            return out
        logger.info("GitForcePushTool: force-pushed %s to %s", refspec, remote)
        return f"Force-pushed {refspec} to {remote}"
