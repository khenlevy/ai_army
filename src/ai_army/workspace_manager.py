"""Helpers for keeping the shared repo clone in a clean, predictable state."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class WorkspacePrepareResult:
    """Result of preparing a shared workspace for a dev run."""

    branch_name: str = ""
    stash_name: str = ""
    stashed_changes: bool = False
    rebased: bool = False
    rebase_conflicts: bool = False
    conflicting_files: list[str] = field(default_factory=list)
    active_branch: str = ""
    message: str = ""


def _lock_path(clone_path: Path) -> Path:
    return clone_path.parent / f".{clone_path.name}.worktree.lock"


def _git_result(repo_path: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run git and return the subprocess result."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git_output(repo_path: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    """Run git and return (returncode, combined output)."""
    result = _git_result(repo_path, *args, timeout=timeout)
    output = "\n".join(
        filter(None, [(result.stdout or "").strip(), (result.stderr or "").strip()])
    )
    return result.returncode, output


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _worktree_dirty(repo_path: Path) -> bool:
    code, output = _git_output(repo_path, "status", "--short")
    return code == 0 and bool(output.strip())


def _current_branch(repo_path: Path) -> str:
    code, output = _git_output(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    return output.strip() if code == 0 else ""


def _conflicting_files(repo_path: Path) -> list[str]:
    code, output = _git_output(repo_path, "diff", "--name-only", "--diff-filter=U")
    if code != 0 or not output.strip():
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _run_or_raise(repo_path: Path, *args: str, timeout: int = 60) -> str:
    code, output = _git_output(repo_path, *args, timeout=timeout)
    if code != 0:
        raise RuntimeError(output or f"git {' '.join(args)} failed")
    return output


def _stash_changes(repo_path: Path, prefix: str) -> tuple[bool, str]:
    """Stash dirty changes and return (stashed, stash_name)."""
    if not _worktree_dirty(repo_path):
        return False, ""
    stash_name = f"{prefix}-{_timestamp_slug()}"
    _run_or_raise(repo_path, "stash", "push", "-u", "-m", stash_name)
    logger.info("WorkspaceManager: stashed dirty worktree in %s as %s", repo_path, stash_name)
    return True, stash_name


def _abort_rebase_if_needed(repo_path: Path) -> bool:
    """Abort an in-progress rebase if one exists."""
    rebase_apply = repo_path / ".git" / "rebase-apply"
    rebase_merge = repo_path / ".git" / "rebase-merge"
    if not rebase_apply.exists() and not rebase_merge.exists():
        return False
    code, output = _git_output(repo_path, "rebase", "--abort", timeout=120)
    if code != 0:
        raise RuntimeError(output or "Failed to abort in-progress rebase")
    logger.info("WorkspaceManager: aborted an in-progress rebase in %s", repo_path)
    return True


def _has_ref(repo_path: Path, ref_name: str) -> bool:
    code, _ = _git_output(repo_path, "rev-parse", "--verify", ref_name)
    return code == 0


@contextmanager
def workspace_lock(clone_path: Path, timeout_seconds: int = 5) -> Iterator[None]:
    """File lock for serializing access to a shared repo clone."""
    path = _lock_path(clone_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError:
            if time.monotonic() - start >= timeout_seconds:
                raise TimeoutError(f"Timed out waiting for workspace lock: {path}")
            time.sleep(1)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def prepare_workspace(
    clone_path: Path,
    branch_name: str | None = None,
    *,
    base_ref: str = "main",
    sync_with_remote: bool = False,
) -> WorkspacePrepareResult:
    """Prepare the shared clone for a dev run.

    The workspace is first normalized to the latest `main`, then optionally the
    target branch is checked out and rebased onto that updated base.
    """
    result = WorkspacePrepareResult(branch_name=branch_name or "")
    _abort_rebase_if_needed(clone_path)
    result.stashed_changes, result.stash_name = _stash_changes(clone_path, "auto-stash")

    _run_or_raise(clone_path, "checkout", base_ref)
    _run_or_raise(clone_path, "pull", "--rebase", "origin", base_ref)
    result.active_branch = base_ref
    result.message = f"Workspace reset to latest {base_ref}."

    if not branch_name:
        return result

    if sync_with_remote:
        _run_or_raise(clone_path, "fetch", "origin", branch_name, timeout=120)

    remote_ref = f"origin/{branch_name}"
    if _has_ref(clone_path, branch_name):
        _run_or_raise(clone_path, "checkout", branch_name)
    elif sync_with_remote and _has_ref(clone_path, remote_ref):
        _run_or_raise(clone_path, "checkout", "-B", branch_name, remote_ref)
    else:
        raise RuntimeError(f"Branch {branch_name} does not exist locally or on origin")

    if sync_with_remote and _has_ref(clone_path, remote_ref):
        _run_or_raise(clone_path, "reset", "--hard", remote_ref)

    result.active_branch = branch_name
    code, output = _git_output(clone_path, "rebase", base_ref, timeout=120)
    if code == 0:
        result.rebased = True
        result.message = f"Branch {branch_name} rebased onto {base_ref}."
        logger.info("WorkspaceManager: rebased %s onto %s", branch_name, base_ref)
        return result

    result.rebase_conflicts = True
    result.conflicting_files = _conflicting_files(clone_path)
    result.message = output or f"Branch {branch_name} has merge conflicts with {base_ref}."
    abort_code, abort_output = _git_output(clone_path, "rebase", "--abort", timeout=120)
    if abort_code != 0:
        logger.warning(
            "WorkspaceManager: failed to abort rebase on %s: %s",
            branch_name,
            abort_output,
        )
    logger.warning(
        "WorkspaceManager: rebase conflicts while preparing %s: %s",
        branch_name,
        ", ".join(result.conflicting_files) or result.message,
    )
    return result


def cleanup_workspace(clone_path: Path) -> str:
    """Return the shared clone to a clean main branch after a run."""
    _abort_rebase_if_needed(clone_path)
    stashed, stash_name = _stash_changes(clone_path, "cleanup-stash")
    _run_or_raise(clone_path, "checkout", "main")
    _run_or_raise(clone_path, "clean", "-fd")
    _run_or_raise(clone_path, "reset", "--hard", "origin/main")
    message = "Workspace cleaned back to origin/main."
    if stashed:
        message += f" Saved dirty state in {stash_name}."
    return message


def fetch_origin(clone_path: Path) -> str:
    """Fetch all refs from origin so remote branches are available for checkout."""
    return _run_or_raise(clone_path, "fetch", "origin", timeout=120)


def force_push_branch(clone_path: Path, branch_name: str) -> str:
    """Force push a rebased branch with safety."""
    return _run_or_raise(
        clone_path,
        "push",
        "--force-with-lease",
        "origin",
        branch_name,
        timeout=120,
    )
