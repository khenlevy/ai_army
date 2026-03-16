"""Tests for repo_clone - ensure 'Cannot rebase onto multiple branches' does not regress."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from ai_army.config.settings import GitHubRepoConfig
from ai_army.repo_clone import ensure_repo_cloned


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return (result.stdout or "").strip()


def _init_remote_and_clone(tmp_path: Path, slug: str) -> tuple[Path, Path]:
    """Create bare remote, seed repo, and clone at workspace/slug."""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    workspace = tmp_path / "workspace"
    clone_path = workspace / slug

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

    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", f"file://{remote.resolve()}", str(clone_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(clone_path, "config", "user.email", "test@example.com")
    _run_git(clone_path, "config", "user.name", "Test User")
    return seed, clone_path


def test_ensure_repo_cloned_does_not_use_pull_rebase(monkeypatch, tmp_path: Path) -> None:
    """Regression: must not use 'git pull --rebase' which causes 'Cannot rebase onto multiple branches'."""
    slug = "owner_repo"
    seed, clone_path = _init_remote_and_clone(tmp_path, slug)
    monkeypatch.setattr("ai_army.repo_clone.settings.repo_workspace", str(tmp_path / "workspace"))
    repo_config = GitHubRepoConfig(token="x", repo="owner/repo")

    with patch("ai_army.repo_clone.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        ensure_repo_cloned(repo_config)

    calls = [tuple(c[0][0]) for c in mock_run.call_args_list]
    pull_rebase_calls = [c for c in calls if "pull" in c and "--rebase" in c]
    assert not pull_rebase_calls, "Must not use 'git pull --rebase' (causes 'Cannot rebase onto multiple branches')"


def test_ensure_repo_cloned_updates_from_feature_branch_to_latest_main(
    monkeypatch, tmp_path: Path
) -> None:
    """When clone is on feature branch (ambiguous state), ensure_repo_cloned updates to latest main."""
    slug = "owner_repo"
    seed, clone_path = _init_remote_and_clone(tmp_path, slug)

    # Put clone on feature branch with local commit (state that triggers rebase ambiguity)
    _run_git(clone_path, "checkout", "-b", "feature/xyz", "origin/main")
    (clone_path / "feature.txt").write_text("feature\n")
    _run_git(clone_path, "add", "feature.txt")
    _run_git(clone_path, "commit", "-m", "feature")

    # Push new commit to main from seed
    _run_git(seed, "checkout", "main")
    (seed / "README.md").write_text("hello updated\n")
    _run_git(seed, "add", "README.md")
    _run_git(seed, "commit", "-m", "main update")
    _run_git(seed, "push", "origin", "main")

    monkeypatch.setattr("ai_army.repo_clone.settings.repo_workspace", str(tmp_path / "workspace"))
    repo_config = GitHubRepoConfig(token="x", repo="owner/repo")

    result = ensure_repo_cloned(repo_config)

    assert result == clone_path
    assert _run_git(clone_path, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _run_git(clone_path, "log", "-1", "--oneline")  # has commits
    # Main should have the "main update" commit
    assert "hello updated" in (clone_path / "README.md").read_text()
