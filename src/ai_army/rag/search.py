"""Search the codebase index via semantic similarity. Falls back to grep when RAG unavailable."""

import json
import logging
import subprocess
import time
from pathlib import Path

from ai_army.config.settings import settings

logger = logging.getLogger(__name__)
RAG_LOG = "[RAG]"

_RAG_AVAILABLE: bool | None = None
_RAG_STATUS_LOGGED: bool = False


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


def _grep_search(repo_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """Fallback: use ripgrep to find files matching query keywords. Returns same shape as RAG search."""
    keywords = [w.strip() for w in query.split() if len(w.strip()) > 2][:6]
    if not keywords:
        return []
    pattern = "|".join(k[:20] for k in keywords)
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


def _workspace_root() -> Path:
    raw = settings.repo_workspace.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve() / ".ai_army_workspace"


def _index_dir_for_repo(repo_path: Path) -> Path:
    workspace = _workspace_root()
    slug = repo_path.name
    return workspace / ".ai_army_index" / slug


def _ensure_fresh_index(repo_path: Path) -> Path:
    """Build index if missing or stale (HEAD changed)."""
    index_dir = _index_dir_for_repo(repo_path)
    meta_path = index_dir / ".meta.json"

    head = None
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        head = r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        pass

    if not meta_path.exists():
        from ai_army.rag.indexer import build_index
        logger.info("%s index missing, building for %s", RAG_LOG, repo_path)
        t0 = time.monotonic()
        result = build_index(repo_path)
        logger.info("%s index build finished (%.1fs)", RAG_LOG, time.monotonic() - t0)
        return result
    try:
        meta = json.loads(meta_path.read_text())
        # Do NOT rebuild when HEAD changed (e.g. feature branch checkout). Index from main
        # is still useful; rebuild blocks Dev crew 15-20 min. Only rebuild when missing.
        if meta.get("last_indexed_commit") != head:
            logger.debug("%s index from different commit (current=%s), reusing", RAG_LOG, head[:8] if head else "?")
    except Exception:
        from ai_army.rag.indexer import build_index
        logger.warning("%s could not read meta, rebuilding index", RAG_LOG)
        t0 = time.monotonic()
        result = build_index(repo_path)
        logger.info("%s index rebuild finished (%.1fs)", RAG_LOG, time.monotonic() - t0)
        return result
    return index_dir


def search(repo_path: Path | str, query: str, top_k: int = 8) -> list[dict]:
    """Search codebase. Returns list of {file_path, start_line, end_line, snippet}. Uses grep when RAG unavailable."""
    repo_path = Path(repo_path).resolve()
    if not query or not query.strip():
        logger.debug("%s empty query, returning []", RAG_LOG)
        return []
    if not (repo_path / ".git").exists():
        logger.warning("%s %s is not a git repo", RAG_LOG, repo_path)
        return []

    use_fallback = getattr(settings, "rag_use_grep_fallback", False) or not _rag_available()
    if use_fallback:
        logger.info("%s using grep fallback | repo=%s", RAG_LOG, repo_path.name)
        return _grep_search(repo_path, query, top_k)

    index_dir = _ensure_fresh_index(repo_path)
    import chromadb
    from sentence_transformers import SentenceTransformer

    t0 = time.monotonic()
    logger.info("%s loading model %s for query", RAG_LOG, settings.rag_embedding_model)
    model = SentenceTransformer(settings.rag_embedding_model)
    logger.info("%s model loaded (%.1fs)", RAG_LOG, time.monotonic() - t0)
    client = chromadb.PersistentClient(path=str(index_dir))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    count = collection.count()
    if count == 0:
        logger.warning("%s index empty for %s", RAG_LOG, repo_path)
        return []

    logger.debug("%s querying index (count=%d, top_k=%d)", RAG_LOG, count, top_k)
    query_embedding = model.encode([query], show_progress_bar=False)
    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=min(top_k, count),
        include=["documents", "metadatas"],
    )

    out: list[dict] = []
    if not results or not results["metadatas"]:
        return out
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
            }
        )
    logger.info("%s returned %d results", RAG_LOG, len(out))
    return out
