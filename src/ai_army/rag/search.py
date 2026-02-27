"""Search the codebase index via semantic similarity."""

import json
import logging
import time
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from ai_army.config.settings import settings
from ai_army.rag.indexer import build_index

logger = logging.getLogger(__name__)
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
        logger.info("rag.search: index missing, building for %s", repo_path)
        t0 = time.monotonic()
        result = build_index(repo_path)
        logger.info("rag.search: index build finished (%.1fs)", time.monotonic() - t0)
        return result
    try:
        meta = json.loads(meta_path.read_text())
        if meta.get("last_indexed_commit") != head:
            logger.info("rag.search: index stale (HEAD changed), rebuilding for %s", repo_path)
            t0 = time.monotonic()
            result = build_index(repo_path)
            logger.info("rag.search: index rebuild finished (%.1fs)", time.monotonic() - t0)
            return result
    except Exception:
        logger.warning("rag.search: could not read meta, rebuilding index")
        t0 = time.monotonic()
        result = build_index(repo_path)
        logger.info("rag.search: index rebuild finished (%.1fs)", time.monotonic() - t0)
        return result
    return index_dir


def search(repo_path: Path | str, query: str, top_k: int = 8) -> list[dict]:
    """Search codebase. Returns list of {file_path, start_line, end_line, snippet}."""
    repo_path = Path(repo_path).resolve()
    if not query or not query.strip():
        logger.debug("rag.search: empty query, returning []")
        return []
    if not (repo_path / ".git").exists():
        logger.warning("rag.search: %s is not a git repo", repo_path)
        return []

    index_dir = _ensure_fresh_index(repo_path)
    t0 = time.monotonic()
    logger.info("rag.search: loading model %s for query", settings.rag_embedding_model)
    model = SentenceTransformer(settings.rag_embedding_model)
    logger.info("rag.search: model loaded (%.1fs)", time.monotonic() - t0)
    client = chromadb.PersistentClient(path=str(index_dir))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    count = collection.count()
    if count == 0:
        logger.warning("rag.search: index empty for %s", repo_path)
        return []

    logger.debug("rag.search: querying index (count=%d, top_k=%d)", count, top_k)
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
    logger.info("rag.search: returned %d results for query", len(out))
    return out
