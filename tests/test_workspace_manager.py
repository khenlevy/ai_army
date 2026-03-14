"""Tests for shared workspace preparation and cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_army import workspace_manager
from ai_army.workspace_manager import cleanup_workspace, prepare_workspace


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return (result.stdout or "").strip()


def _init_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True, text=True)
    _run_git(seed, "config", "user.email", "test@example.com")
    _run_git(seed, "config", "user.name", "Test User")
    (seed / "README.md").write_text("hello\n")
    _run_git(seed, "add", "README.md")
    _run_git(seed, "commit", "-m", "init")
    _run_git(seed, "branch", "-M", "main")
    _run_git(seed, "remote", "add", "origin", str(remote))
    _run_git(seed, "push", "-u", "origin", "main")

    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True, text=True)
    _run_git(clone, "config", "user.email", "test@example.com")
    _run_git(clone, "config", "user.name", "Test User")
    _run_git(clone, "checkout", "main")
    return seed, clone


def test_prepare_workspace_rebases_branch_and_cleanup_resets_main(tmp_path: Path) -> None:
    """Existing work branches should be rebased onto latest main and cleanup should reset the clone."""
    seed, clone = _init_remote_and_clone(tmp_path)

    _run_git(clone, "checkout", "-b", "feature/issue-1-test", "main")
    (clone / "feature.txt").write_text("feature work\n")
    _run_git(clone, "add", "feature.txt")
    _run_git(clone, "commit", "-m", "feature commit")

    _run_git(seed, "checkout", "main")
    (seed / "README.md").write_text("hello from main\n")
    _run_git(seed, "add", "README.md")
    _run_git(seed, "commit", "-m", "main update")
    _run_git(seed, "push", "origin", "main")

    result = prepare_workspace(clone, "feature/issue-1-test")

    assert result.rebased is True
    assert result.rebase_conflicts is False
    assert result.active_branch == "feature/issue-1-test"
    assert _run_git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "feature/issue-1-test"

    cleanup_workspace(clone)

    assert _run_git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _run_git(clone, "status", "--short") == ""


def test_prepare_workspace_stashes_dirty_changes(tmp_path: Path) -> None:
    """Dirty worktrees should be stashed before the workspace is normalized."""
    _, clone = _init_remote_and_clone(tmp_path)

    (clone / "scratch.txt").write_text("leftover work\n")

    result = prepare_workspace(clone)

    assert result.stashed_changes is True
    assert result.stash_name.startswith("auto-stash-")
    assert "auto-stash-" in _run_git(clone, "stash", "list")


def test_cleanup_workspace_aborts_rebase_before_stashing(monkeypatch) -> None:
    """Cleanup should abort rebases before attempting to stash conflicted files."""
    call_order: list[str] = []

    monkeypatch.setattr(
        workspace_manager,
        "_abort_rebase_if_needed",
        lambda _clone_path: call_order.append("abort"),
    )
    monkeypatch.setattr(
        workspace_manager,
        "_stash_changes",
        lambda _clone_path, _prefix: (call_order.append("stash") or True, "cleanup-stash-test"),
    )
    monkeypatch.setattr(
        workspace_manager,
        "_run_or_raise",
        lambda _clone_path, *_args, **_kwargs: call_order.append("run"),
    )

    cleanup_workspace(Path("/tmp/repo"))

    assert call_order[:2] == ["abort", "stash"]
