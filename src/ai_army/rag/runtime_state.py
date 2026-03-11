"""Shared runtime state for RAG indexing, published snapshots, and agent readiness."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ai_army.config.settings import GitHubRepoConfig, settings

logger = logging.getLogger(__name__)
RAG_LOG = "[RAG]"
INDEX_DIR_NAME = ".ai_army_index"
SNAPSHOTS_DIR_NAME = "snapshots"
RUNTIME_STATE_FILE = "runtime_state.json"
ACTIVE_SNAPSHOT_FILE = "active_snapshot.json"
BUILD_LOCK_FILE = ".build.lock"


@dataclass
class RepoCapabilities:
    """Validated agent capabilities for a repo execution window."""

    search_ready: bool = False
    issue_ops_ready: bool = False
    code_ops_ready: bool = False
    pr_ops_ready: bool = False
    review_ops_ready: bool = False


@dataclass
class RepoRuntimeState:
    """Persisted runtime state for a repo's search/index lifecycle."""

    repo_key: str
    repo_name: str = ""
    repo_path: str = ""
    index_state: str = "index_bootstrapping"
    agent_state: str = "agents_blocked_for_index_window"
    sync_state: str = "sync_catchup_needed"
    retrieval_mode: str = "unavailable"
    snapshot_version: str = ""
    source_commit: str = ""
    active_snapshot_dir: str = ""
    published_at: str = ""
    next_agent_window_at: str = ""
    last_build_started_at: str = ""
    last_build_finished_at: str = ""
    last_validation_at: str = ""
    last_error: str = ""
    capabilities: RepoCapabilities = field(default_factory=RepoCapabilities)

    def to_dict(self) -> dict[str, Any]:
        """Serialize runtime state for JSON persistence."""
        data = asdict(self)
        data["capabilities"] = asdict(self.capabilities)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], repo_key: str) -> "RepoRuntimeState":
        """Hydrate runtime state from JSON."""
        capabilities = RepoCapabilities(**(data.get("capabilities") or {}))
        return cls(
            repo_key=repo_key,
            repo_name=data.get("repo_name", ""),
            repo_path=data.get("repo_path", ""),
            index_state=data.get("index_state", "index_bootstrapping"),
            agent_state=data.get("agent_state", "agents_blocked_for_index_window"),
            sync_state=data.get("sync_state", "sync_catchup_needed"),
            retrieval_mode=data.get("retrieval_mode", "unavailable"),
            snapshot_version=data.get("snapshot_version", ""),
            source_commit=data.get("source_commit", ""),
            active_snapshot_dir=data.get("active_snapshot_dir", ""),
            published_at=data.get("published_at", ""),
            next_agent_window_at=data.get("next_agent_window_at", ""),
            last_build_started_at=data.get("last_build_started_at", ""),
            last_build_finished_at=data.get("last_build_finished_at", ""),
            last_validation_at=data.get("last_validation_at", ""),
            last_error=data.get("last_error", ""),
            capabilities=capabilities,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    tmp_path.replace(path)


def workspace_root() -> Path:
    """Shared workspace root for clones and RAG artifacts."""
    raw = settings.repo_workspace.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve() / ".ai_army_workspace"


def repo_slug(repo: str | Path) -> str:
    """Stable slug for repo state files and index roots."""
    if isinstance(repo, Path):
        return repo.name
    return repo.replace("/", "_")


def repo_index_root(repo: str | Path) -> Path:
    root = workspace_root() / INDEX_DIR_NAME / repo_slug(repo)
    root.mkdir(parents=True, exist_ok=True)
    return root


def snapshots_root(repo: str | Path) -> Path:
    root = repo_index_root(repo) / SNAPSHOTS_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def runtime_state_path(repo: str | Path) -> Path:
    return repo_index_root(repo) / RUNTIME_STATE_FILE


def active_snapshot_path(repo: str | Path) -> Path:
    return repo_index_root(repo) / ACTIVE_SNAPSHOT_FILE


def build_lock_path(repo: str | Path) -> Path:
    return repo_index_root(repo) / BUILD_LOCK_FILE


def snapshot_meta_path(snapshot_dir: Path) -> Path:
    return snapshot_dir / ".meta.json"


def build_window_opens_at() -> str:
    delay_minutes = max(settings.rag_agent_window_delay_minutes, 0)
    return (_utc_now() + timedelta(minutes=delay_minutes)).isoformat()


def load_runtime_state(repo: str | Path) -> RepoRuntimeState:
    """Load runtime state or return a default object."""
    key = repo_slug(repo)
    path = runtime_state_path(repo)
    if not path.exists():
        return RepoRuntimeState(repo_key=key)
    try:
        payload = json.loads(path.read_text())
        return RepoRuntimeState.from_dict(payload, repo_key=key)
    except Exception as exc:
        logger.warning("%s failed to read runtime state for %s: %s", RAG_LOG, key, exc)
        return RepoRuntimeState(repo_key=key, index_state="index_failed", last_error=str(exc))


def save_runtime_state(repo: str | Path, state: RepoRuntimeState) -> RepoRuntimeState:
    """Persist runtime state atomically."""
    _write_json_atomic(runtime_state_path(repo), state.to_dict())
    return state


def load_active_snapshot(repo: str | Path) -> dict[str, Any] | None:
    """Read the published snapshot pointer for a repo."""
    path = active_snapshot_path(repo)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.warning("%s failed to read active snapshot pointer for %s: %s", RAG_LOG, repo_slug(repo), exc)
        return None


def publish_active_snapshot(repo: str | Path, payload: dict[str, Any]) -> None:
    """Publish a new active snapshot pointer atomically."""
    _write_json_atomic(active_snapshot_path(repo), payload)


def cleanup_staging_dir(path: Path) -> None:
    """Best-effort cleanup for failed staging builds."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def current_head_commit(repo_path: Path) -> str | None:
    """Get current HEAD commit for the local clone."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def git_repo_usable(repo_path: Path) -> bool:
    """Check that a local clone is readable and git-aware."""
    if not (repo_path / ".git").exists():
        return False
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def lexical_fallback_available() -> bool:
    """Return True when a lexical fallback implementation is available."""
    return shutil.which("rg") is not None or shutil.which("grep") is not None


def snapshot_is_fresh(repo_path: Path, source_commit: str) -> bool:
    """Treat matching HEAD as fresh; otherwise search is still usable but stale."""
    head = current_head_commit(repo_path)
    return bool(head and source_commit and head == source_commit)


def snapshot_dir_for_version(repo: str | Path, version: str) -> Path:
    return snapshots_root(repo) / version


def staging_snapshot_dir(repo: str | Path, version: str) -> Path:
    return snapshots_root(repo) / f".staging-{version}"


@contextmanager
def build_lock(repo: str | Path, timeout_seconds: int = 30) -> Iterator[None]:
    """Simple file lock for single-host build/publish operations."""
    lock_path = build_lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError:
            if time.monotonic() - start >= timeout_seconds:
                raise TimeoutError(f"Timed out waiting for RAG build lock: {lock_path}")
            time.sleep(1)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _repo_permission_set(repo: Any) -> set[str]:
    raw = getattr(repo, "permissions", None) or {}
    if isinstance(raw, dict):
        return {name for name, allowed in raw.items() if allowed}
    if hasattr(raw, "__dict__"):
        return {name for name, allowed in vars(raw).items() if allowed}
    return set()


def validate_runtime_state(
    repo_path: Path,
    repo_config: GitHubRepoConfig | None = None,
) -> RepoRuntimeState:
    """Validate published search state plus agent mutation capabilities."""
    key = repo_slug(repo_path)
    state = load_runtime_state(key)
    state.repo_key = key
    state.repo_name = repo_config.repo if repo_config else state.repo_name
    state.repo_path = str(repo_path)
    state.last_validation_at = _utc_now_iso()
    state.last_error = ""

    active_snapshot = load_active_snapshot(key)
    retrieval_mode = "unavailable"
    search_ready = False
    index_state = state.index_state
    sync_state = "sync_catchup_needed"
    snapshot_version = ""
    active_snapshot_dir = ""
    source_commit = ""
    published_at = ""

    if active_snapshot and not settings.rag_use_grep_fallback:
        active_snapshot_dir = active_snapshot.get("snapshot_dir", "")
        snapshot_version = active_snapshot.get("snapshot_version", "")
        source_commit = active_snapshot.get("source_commit", "")
        published_at = active_snapshot.get("published_at", "")
        snapshot_dir = Path(active_snapshot_dir)
        if snapshot_dir.exists():
            if snapshot_is_fresh(repo_path, source_commit):
                retrieval_mode = "semantic_fresh"
                index_state = "index_published_fresh"
                sync_state = "sync_clean"
            else:
                retrieval_mode = "semantic_stale"
                index_state = "index_published_stale"
                sync_state = "sync_catchup_needed"
            search_ready = True

    if (settings.rag_use_grep_fallback or not search_ready) and lexical_fallback_available():
        retrieval_mode = "lexical_fallback"
        index_state = "index_degraded"
        search_ready = True

    code_ops_ready = git_repo_usable(repo_path) and os.access(repo_path, os.W_OK)
    issue_ops_ready = False
    pr_ops_ready = False
    review_ops_ready = False
    if repo_config:
        try:
            from ai_army.tools.github_helpers import get_repo_from_config

            repo = get_repo_from_config(repo_config)
            perms = _repo_permission_set(repo)
            issue_ops_ready = bool({"admin", "maintain", "push", "triage"} & perms)
            pr_ops_ready = bool({"admin", "maintain", "push"} & perms)
            review_ops_ready = bool({"admin", "maintain", "push", "triage", "pull"} & perms)
        except Exception as exc:
            state.last_error = f"GitHub validation failed: {exc}"
            logger.warning("%s GitHub capability validation failed for %s: %s", RAG_LOG, repo_config.repo, exc)

    state.snapshot_version = snapshot_version
    state.active_snapshot_dir = active_snapshot_dir
    state.source_commit = source_commit
    state.published_at = published_at
    state.retrieval_mode = retrieval_mode
    state.index_state = index_state
    state.sync_state = sync_state
    state.capabilities = RepoCapabilities(
        search_ready=search_ready,
        issue_ops_ready=issue_ops_ready,
        code_ops_ready=code_ops_ready,
        pr_ops_ready=pr_ops_ready,
        review_ops_ready=review_ops_ready,
    )

    if not search_ready:
        state.agent_state = "agents_blocked_for_index_window"
    elif retrieval_mode == "lexical_fallback":
        state.agent_state = "agents_degraded_search"
    elif issue_ops_ready or code_ops_ready or pr_ops_ready or review_ops_ready:
        state.agent_state = "agents_ready"
    else:
        state.agent_state = "agents_paused_due_to_inconsistency"

    save_runtime_state(key, state)
    return state


def mark_build_started(repo: str | Path, repo_name: str = "", repo_path: str = "") -> RepoRuntimeState:
    """Persist the beginning of a new indexing cycle."""
    state = load_runtime_state(repo)
    state.repo_name = repo_name or state.repo_name
    state.repo_path = repo_path or state.repo_path
    state.index_state = "index_building"
    state.agent_state = "agents_blocked_for_index_window"
    state.sync_state = "sync_locked_for_publish"
    state.last_build_started_at = _utc_now_iso()
    state.next_agent_window_at = ""
    state.last_error = ""
    return save_runtime_state(repo, state)


def mark_build_failed(repo: str | Path, error: str) -> RepoRuntimeState:
    """Persist build failure without destroying the last good snapshot."""
    state = load_runtime_state(repo)
    state.index_state = "index_failed"
    state.last_error = error
    state.last_build_finished_at = _utc_now_iso()
    return save_runtime_state(repo, state)


def mark_snapshot_published(
    repo: str | Path,
    *,
    repo_name: str,
    repo_path: str,
    snapshot_version: str,
    snapshot_dir: Path,
    source_commit: str,
) -> RepoRuntimeState:
    """Persist the new published snapshot and reopen the next agent window."""
    state = load_runtime_state(repo)
    state.repo_name = repo_name or state.repo_name
    state.repo_path = repo_path
    state.snapshot_version = snapshot_version
    state.active_snapshot_dir = str(snapshot_dir)
    state.source_commit = source_commit or ""
    state.published_at = _utc_now_iso()
    state.last_build_finished_at = state.published_at
    state.next_agent_window_at = build_window_opens_at()
    state.last_error = ""
    return save_runtime_state(repo, state)


def open_agent_window(repo: str | Path) -> RepoRuntimeState:
    """Open the next agent window after refresh finishes, including degraded mode."""
    state = load_runtime_state(repo)
    state.next_agent_window_at = build_window_opens_at()
    return save_runtime_state(repo, state)


def agent_window_open(state: RepoRuntimeState) -> bool:
    """True once the validated execution window has opened."""
    if not state.next_agent_window_at:
        return False
    opens_at = _parse_iso(state.next_agent_window_at)
    return bool(opens_at and _utc_now() >= opens_at)


def repo_key_for_config(repo_config: GitHubRepoConfig) -> str:
    """Stable state key for a configured GitHub repository."""
    return repo_slug(repo_config.repo)
