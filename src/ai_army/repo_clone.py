"""Clone target repos so dev crew can work like humans (branch, commit, push in a real clone)."""

import logging
import subprocess
import time
from pathlib import Path

from ai_army.config.settings import get_github_repos, settings
from ai_army.config.settings import GitHubRepoConfig

logger = logging.getLogger(__name__)

# If index.lock is older than this (seconds), treat as stale from crashed process
GIT_INDEX_LOCK_STALE_SECONDS = 120


def _workspace_root() -> Path:
    """Directory where we clone target repos. Default: .ai_army_workspace in cwd."""
    raw = settings.repo_workspace.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve() / ".ai_army_workspace"


def _clone_url_with_auth(repo_config: GitHubRepoConfig) -> str:
    """HTTPS clone URL with token for push/fetch (works for private repos)."""
    # owner/repo -> https://x-access-token:TOKEN@github.com/owner/repo.git
    return f"https://x-access-token:{repo_config.token}@github.com/{repo_config.repo}.git"


def ensure_repo_cloned(repo_config: GitHubRepoConfig | None = None) -> Path | None:
    """Ensure the target repo is cloned in the workspace; return its path.

    If repo_config is None, uses the first repo from get_github_repos().
    Creates workspace dir, clones if missing, runs git pull if already present.
    Returns None if no repo config is available.
    """
    if repo_config is None:
        repos = get_github_repos()
        if not repos:
            logger.warning("ensure_repo_cloned: no GitHub repos configured")
            return None
        repo_config = repos[0]

    workspace = _workspace_root()
    workspace.mkdir(parents=True, exist_ok=True)
    slug = repo_config.repo.replace("/", "_")
    clone_path = workspace / slug

    if (clone_path / ".git").exists():
        logger.info("Repo already cloned at %s, pulling latest", clone_path)
        # Remove stale index.lock from crashed/interrupted git (e.g. container restart)
        index_lock = clone_path / ".git" / "index.lock"
        if index_lock.exists():
            age = time.time() - index_lock.stat().st_mtime
            if age > GIT_INDEX_LOCK_STALE_SECONDS:
                try:
                    index_lock.unlink()
                    logger.info("Removed stale .git/index.lock (age %.0fs)", age)
                except OSError as e:
                    logger.warning("Could not remove stale index.lock: %s", e)
        # Use fetch + reset instead of "git pull --rebase" to avoid
        # "Cannot rebase onto multiple branches" when clone is in ambiguous state
        # (e.g. left on feature branch, detached HEAD, or concurrent fetch).
        r = subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=clone_path,
            capture_output=True,
            timeout=30,
        )
        # Ignore abort result; only matters if we were mid-rebase
        r = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=clone_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            logger.warning("git fetch failed in %s: %s", clone_path, r.stderr)
            return clone_path
        # Reset to origin's default branch (main or master)
        default_ref = "origin/main"
        ref_check = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            cwd=clone_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if ref_check.returncode == 0 and ref_check.stdout.strip():
            default_ref = ref_check.stdout.strip()
        branch_name = default_ref.replace("origin/", "")
        r = subprocess.run(
            ["git", "checkout", "-B", branch_name, default_ref],
            cwd=clone_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0 and default_ref != "origin/main":
            r = subprocess.run(
                ["git", "checkout", "-B", "main", "origin/main"],
                cwd=clone_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        if r.returncode != 0:
            logger.warning("git checkout/reset failed in %s: %s", clone_path, r.stderr)
        else:
            logger.info("ensure_repo_cloned: pulled latest at %s", clone_path)
        return clone_path

    url = _clone_url_with_auth(repo_config)
    logger.info("Cloning %s to %s", repo_config.repo, clone_path)
    r = subprocess.run(
        ["git", "clone", url, str(clone_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        logger.error("git clone failed: %s", r.stderr)
        return None
    logger.info("ensure_repo_cloned: successfully cloned %s to %s", repo_config.repo, clone_path)
    return clone_path
