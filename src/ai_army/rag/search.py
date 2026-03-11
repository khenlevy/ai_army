"""Search the published codebase snapshot via semantic similarity or lexical fallback."""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ai_army.config.settings import settings
from ai_army.rag.runtime_state import (
    RAG_LOG,
    load_active_snapshot,
    validate_runtime_state,
)

logger = logging.getLogger(__name__)
_RAG_AVAILABLE: bool | None = None
_RAG_STATUS_LOGGED: bool = False
_QUERY_MODEL = None


def _rag_available() -> bool:
    """Check if RAG deps (sentence_transformers, chromadb) are importable."""
    global _RAG_AVAILABLE
    if _RAG_AVAILABLE is not None:
        return _RAG_AVAILABLE
    try:
        import chromadb  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        _RAG_AVAILABLE = True
    except ImportError:
        _RAG_AVAILABLE = False
    return _RAG_AVAILABLE


def log_rag_status() -> None:
    """Log RAG mode at startup. Grep for [RAG] on droplet to see status quickly."""
    global _RAG_STATUS_LOGGED
    if _RAG_STATUS_LOGGED:
        return
    _RAG_STATUS_LOGGED = True
    use_fallback = getattr(settings, "rag_use_grep_fallback", False)
    deps_ok = _rag_available()
    if use_fallback:
        logger.info("%s mode=fallback (RAG_USE_GREP_FALLBACK=1) | codebase search uses grep", RAG_LOG)
    elif not deps_ok:
        logger.info("%s mode=fallback (deps unavailable) | codebase search uses grep", RAG_LOG)
    else:
        logger.info("%s mode=semantic | codebase search uses embedding model %s", RAG_LOG, settings.rag_embedding_model)


@dataclass
class SearchResponse:
    """Structured search response with retrieval metadata for agent logs."""

    results: list[dict]
    retrieval_mode: str
    snapshot_version: str = ""
    index_state: str = ""


def _grep_search(repo_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """Fallback: use ripgrep to find files matching query keywords. Returns same shape as RAG search."""
    keywords = [w.strip() for w in query.split() if len(w.strip()) > 2][:6]
    if not keywords:
        return []
    escaped = [re.escape(k[:20]) for k in keywords]
    pattern = "|".join(escaped)
    exclude = ["-g", "!node_modules", "-g", "!.yarn", "-g", "!.git", "-g", "!*/.cache/*"]
    logger.info("%s grep fallback | repo=%s keywords=%s", RAG_LOG, repo_path.name, keywords[:4])
    try:
        r = subprocess.run(
            ["rg", "-n", "-m", str(top_k * 3)] + exclude + [pattern, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
    except FileNotFoundError:
        try:
            r = subprocess.run(
                ["grep", "-rn", "-m", str(top_k * 3), pattern, str(repo_path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_path,
            )
        except FileNotFoundError:
            logger.warning("%s neither rg nor grep found", RAG_LOG)
            return []
    if r.returncode not in (0, 1):
        return []
    out: list[dict] = []
    for line in r.stdout.strip().splitlines()[: top_k * 3]:
        parts = line.split(":", 2)
        if len(parts) >= 2:
            fp, ln = parts[0], parts[1]
            snippet = parts[2] if len(parts) > 2 else ""
            out.append({"file_path": fp, "start_line": int(ln) if ln.isdigit() else 0, "end_line": 0, "snippet": snippet})
        if len(out) >= top_k:
            break
    return out[:top_k]
COLLECTION_NAME = "codebase"
MAX_SNIPPET_LINES = 30
QUERY_COLLECTION_NAME = COLLECTION_NAME


def _get_query_model():
    """Cache the query embedding model across searches."""
    global _QUERY_MODEL
    if _QUERY_MODEL is None:
        from sentence_transformers import SentenceTransformer

        t0 = time.monotonic()
        logger.info("%s loading model %s for query", RAG_LOG, settings.rag_embedding_model)
        _QUERY_MODEL = SentenceTransformer(settings.rag_embedding_model)
        logger.info("%s model loaded (%.1fs)", RAG_LOG, time.monotonic() - t0)
    return _QUERY_MODEL


def query_codebase(repo_path: Path | str, query: str, top_k: int = 8) -> SearchResponse:
    """Search codebase with retrieval metadata. Never builds indexes inline."""
    repo_path = Path(repo_path).resolve()
    if not query or not query.strip():
        logger.debug("%s empty query, returning []", RAG_LOG)
        return SearchResponse(results=[], retrieval_mode="empty_query")
    if not (repo_path / ".git").exists():
        logger.warning("%s %s is not a git repo", RAG_LOG, repo_path)
        return SearchResponse(results=[], retrieval_mode="invalid_repo")

    state = validate_runtime_state(repo_path)
    if state.retrieval_mode.startswith("semantic") and _rag_available():
        active_snapshot = load_active_snapshot(repo_path)
        snapshot_dir = Path(active_snapshot.get("snapshot_dir", "")) if active_snapshot else None
        if snapshot_dir and snapshot_dir.exists():
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(snapshot_dir))
                collection = client.get_or_create_collection(
                    QUERY_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
                )
                count = collection.count()
                if count > 0:
                    logger.debug("%s querying snapshot %s (count=%d, top_k=%d)", RAG_LOG, state.snapshot_version, count, top_k)
                    model = _get_query_model()
                    query_embedding = model.encode([query], show_progress_bar=False)
                    results = collection.query(
                        query_embeddings=query_embedding.tolist(),
                        n_results=min(top_k, count),
                        include=["documents", "metadatas"],
                    )
                    out: list[dict] = []
                    if results and results.get("metadatas"):
                        for meta_list, doc_list in zip(results["metadatas"][0], results["documents"][0]):
                            if not meta_list or not doc_list:
                                continue
                            snippet = doc_list
                            lines = snippet.splitlines()
                            if len(lines) > MAX_SNIPPET_LINES:
                                snippet = "\n".join(lines[:MAX_SNIPPET_LINES]) + "\n..."
                            out.append(
                                {
                                    "file_path": meta_list.get("file_path", ""),
                                    "start_line": meta_list.get("start_line", 0),
                                    "end_line": meta_list.get("end_line", 0),
                                    "snippet": snippet,
                                    "language": meta_list.get("language", ""),
                                    "symbol_name": meta_list.get("symbol_name", ""),
                                }
                            )
                    logger.info("%s returned %d results | mode=%s snapshot=%s", RAG_LOG, len(out), state.retrieval_mode, state.snapshot_version)
                    return SearchResponse(
                        results=out,
                        retrieval_mode=state.retrieval_mode,
                        snapshot_version=state.snapshot_version,
                        index_state=state.index_state,
                    )
            except Exception as exc:
                logger.warning("%s semantic query failed for %s, degrading to lexical fallback: %s", RAG_LOG, repo_path.name, exc)

    logger.info("%s using lexical fallback | repo=%s", RAG_LOG, repo_path.name)
    return SearchResponse(
        results=_grep_search(repo_path, query, top_k),
        retrieval_mode="lexical_fallback",
        snapshot_version=state.snapshot_version,
        index_state=state.index_state,
    )


def search(repo_path: Path | str, query: str, top_k: int = 8) -> list[dict]:
    """Compatibility wrapper returning only result rows."""
    return query_codebase(repo_path, query, top_k=top_k).results
