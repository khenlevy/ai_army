"""Refresh published RAG snapshots and validate agent readiness."""

import logging
import threading
import time

from ai_army.config import get_github_repos
from ai_army.config.settings import settings
from ai_army.rag.runtime_state import (
    RAG_LOG,
    mark_build_failed,
    open_agent_window,
    repo_key_for_config,
    validate_runtime_state,
)
from ai_army.repo_clone import ensure_repo_cloned

logger = logging.getLogger(__name__)


def refresh_indexes() -> None:
    """Refresh repo snapshots in the dedicated indexing plane."""
    repos = get_github_repos()
    if not repos:
        return

    for repo_config in repos:
        t0 = time.monotonic()
        logger.info("%s refresh started for %s", RAG_LOG, repo_config.repo)
        clone_path = None
        try:
            clone_path = ensure_repo_cloned(repo_config)
            if not clone_path:
                logger.warning("%s refresh skipped for %s (clone failed)", RAG_LOG, repo_config.repo)
                continue

            if getattr(settings, "rag_use_grep_fallback", False):
                state = validate_runtime_state(clone_path, repo_config=repo_config)
                open_agent_window(repo_key_for_config(repo_config))
                logger.info(
                    "%s refresh done for %s in lexical fallback mode (%.1fs)",
                    RAG_LOG,
                    repo_config.repo,
                    time.monotonic() - t0,
                )
                logger.info("%s state=%s mode=%s", RAG_LOG, state.index_state, state.retrieval_mode)
                continue

            from ai_army.rag.indexer import build_index

            build_index(clone_path)
            state = validate_runtime_state(clone_path, repo_config=repo_config)
            elapsed = time.monotonic() - t0
            logger.info(
                "%s refresh done for %s (%.1fs) | state=%s mode=%s",
                RAG_LOG,
                repo_config.repo,
                elapsed,
                state.index_state,
                state.retrieval_mode,
            )
        except Exception as e:
            mark_build_failed(repo_key_for_config(repo_config), str(e))
            if clone_path:
                validate_runtime_state(clone_path, repo_config=repo_config)
                open_agent_window(repo_key_for_config(repo_config))
            logger.warning("%s refresh failed for %s: %s", RAG_LOG, repo_config.repo, e)


def prebuild_indexes() -> None:
    """Compatibility helper: start an async refresh on startup."""
    thread = threading.Thread(target=refresh_indexes, daemon=True)
    thread.start()
    logger.info("%s refresh started in background", RAG_LOG)
