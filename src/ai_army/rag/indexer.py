"""Build and persist ChromaDB index for a repo."""

import json
import logging
import subprocess
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from ai_army.config.settings import settings
from ai_army.rag.chunker import chunk_file, should_index_path

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "codebase"


def _workspace_root() -> Path:
    """Workspace directory (same as repo_clone)."""
    raw = settings.repo_workspace.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve() / ".ai_army_workspace"


def _index_dir_for_repo(repo_path: Path) -> Path:
    """Index directory: {workspace}/.ai_army_index/{slug}/."""
    workspace = _workspace_root()
    slug = repo_path.name
    return workspace / ".ai_army_index" / slug


def _get_head_commit(repo_path: Path) -> str | None:
    """Get current HEAD commit hash."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def build_index(repo_path: Path) -> Path:
    """Build ChromaDB index for the repo. Returns index directory path."""
    repo_path = Path(repo_path).resolve()
    if not (repo_path / ".git").exists():
        logger.error("build_index: %s is not a git repo", repo_path)
        raise ValueError(f"Not a git repo: {repo_path}")

    index_dir = _index_dir_for_repo(repo_path)
    index_dir.mkdir(parents=True, exist_ok=True)

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=str(index_dir))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )
    existing = collection.get()
    if existing["ids"]:
        collection.delete(existing["ids"])

    texts: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for fpath in repo_path.rglob("*"):
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(repo_path)
        if not should_index_path(rel):
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug("build_index: skipped %s: %s", rel, e)
            continue
        for i, chunk in enumerate(chunk_file(rel.as_posix(), content)):
            chunk_id = f"{rel.as_posix()}:{chunk.start_line}"
            texts.append(chunk.text)
            metadatas.append(
                {
                    "file_path": rel.as_posix(),
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "symbol_name": chunk.symbol_name or "",
                }
            )
            ids.append(chunk_id)

    if not texts:
        logger.warning("build_index: no indexable files found in %s", repo_path)
    else:
        embeddings = model.encode(texts, show_progress_bar=False)
        collection.add(ids=ids, embeddings=embeddings.tolist(), documents=texts, metadatas=metadatas)

    head = _get_head_commit(repo_path)
    meta_path = index_dir / ".meta.json"
    meta_path.write_text(json.dumps({"last_indexed_commit": head or ""}))

    logger.info("Indexed %d chunks from %s", len(ids), repo_path)
    return index_dir
