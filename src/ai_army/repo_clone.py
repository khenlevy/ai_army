"""Clone target repos so dev crew can work like humans (branch, commit, push in a real clone)."""

import logging
import subprocess
from pathlib import Path

from ai_army.config.settings import get_github_repos, settings
from ai_army.config.settings import GitHubRepoConfig

logger = logging.getLogger(__name__)


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
            return None
        repo_config = repos[0]

    workspace = _workspace_root()
    workspace.mkdir(parents=True, exist_ok=True)
    slug = repo_config.repo.replace("/", "_")
    clone_path = workspace / slug

    if (clone_path / ".git").exists():
        logger.info("Repo already cloned at %s, pulling latest.", clone_path)
        r = subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=clone_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            logger.warning("git pull failed in %s: %s", clone_path, r.stderr)
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
    return clone_path
