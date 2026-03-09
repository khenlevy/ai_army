"""Pre-build RAG indexes at startup so Dev crew gets instant semantic search."""

import logging
import threading
import time

from ai_army.config import get_github_repos
from ai_army.config.settings import settings
from ai_army.repo_clone import ensure_repo_cloned

logger = logging.getLogger(__name__)
RAG_LOG = "[RAG]"


def _run_prebuild() -> None:
    """Build RAG indexes for all configured repos. Runs in background thread."""
    if getattr(settings, "rag_use_grep_fallback", False):
        logger.info("%s prebuild skipped (RAG_USE_GREP_FALLBACK=1)", RAG_LOG)
        return
    try:
        from ai_army.rag.indexer import build_index
    except ImportError:
        logger.info("%s prebuild skipped (RAG deps unavailable)", RAG_LOG)
        return

    repos = get_github_repos()
    if not repos:
        return

    for repo_config in repos:
        t0 = time.monotonic()
        logger.info("%s prebuild started for %s", RAG_LOG, repo_config.repo)
        try:
            clone_path = ensure_repo_cloned(repo_config)
            if clone_path:
                build_index(clone_path)
                elapsed = time.monotonic() - t0
                logger.info("%s prebuild done for %s (%.1fs)", RAG_LOG, repo_config.repo, elapsed)
            else:
                logger.warning("%s prebuild skipped for %s (clone failed)", RAG_LOG, repo_config.repo)
        except Exception as e:
            logger.warning("%s prebuild failed for %s: %s", RAG_LOG, repo_config.repo, e)


def prebuild_indexes() -> None:
    """Start RAG index prebuild in background. Scheduler starts immediately; index builds in parallel."""
    thread = threading.Thread(target=_run_prebuild, daemon=True)
    thread.start()
    logger.info("%s prebuild started in background", RAG_LOG)
