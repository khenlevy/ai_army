"""Build and publish versioned ChromaDB snapshots for a repo."""

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from ai_army.config.settings import settings

COMPACTION_ERROR_HINT = (
    " Set RAG_USE_GREP_FALLBACK=1 in .env.production to skip ChromaDB and use grep-based search."
)
from ai_army.rag.chunker import chunk_file, should_index_path
from ai_army.rag.runtime_state import (
    RAG_LOG,
    build_lock,
    cleanup_staging_dir,
    current_head_commit,
    load_runtime_state,
    mark_build_failed,
    mark_build_started,
    mark_snapshot_published,
    publish_active_snapshot,
    repo_slug,
    save_runtime_state,
    snapshot_dir_for_version,
    snapshot_meta_path,
    staging_snapshot_dir,
    validate_runtime_state,
)

logger = logging.getLogger(__name__)
COLLECTION_NAME = "codebase"
BATCH_SIZE = 256
INDEX_SCHEMA_VERSION = 2
_MODEL: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Cache the embedding model across builds in this process."""
    global _MODEL
    if _MODEL is None:
        t_load = time.monotonic()
        _MODEL = SentenceTransformer(settings.rag_embedding_model)
        logger.info("%s build model loaded %s (%.1fs)", RAG_LOG, settings.rag_embedding_model, time.monotonic() - t_load)
    return _MODEL


def _language_for_path(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "text"


def _sha1_text(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()


def _flush_batch(
    collection,
    model: SentenceTransformer,
    texts: list[str],
    metadatas: list[dict],
    ids: list[str],
) -> int:
    if not texts:
        return 0
    embeddings = model.encode(texts, show_progress_bar=False)
    collection.add(ids=ids, embeddings=embeddings.tolist(), documents=texts, metadatas=metadatas)
    size = len(texts)
    texts.clear()
    metadatas.clear()
    ids.clear()
    return size


def _is_chromadb_compaction_error(exc: BaseException) -> bool:
    """Check if the error is ChromaDB's known compaction bug (large datasets)."""
    return isinstance(exc, chromadb.errors.InternalError) and "compaction" in str(exc).lower()


def _build_index_inner(repo_path: Path, batch_size: int) -> Path:
    """Build and publish a versioned ChromaDB snapshot. Used by build_index with retry."""
    t0 = time.monotonic()
    repo_path = Path(repo_path).resolve()
    if not (repo_path / ".git").exists():
        logger.error("build_index: %s is not a git repo", repo_path)
        raise ValueError(f"Not a git repo: {repo_path}")

    repo_key = repo_slug(repo_path)
    mark_build_started(repo_key, repo_name=repo_key, repo_path=str(repo_path))
    head = current_head_commit(repo_path) or ""
    version = f"{int(time.time())}-{head[:8] or 'snapshot'}"
    staging_dir = staging_snapshot_dir(repo_key, version)
    final_dir = snapshot_dir_for_version(repo_key, version)
    cleanup_staging_dir(staging_dir)
    shutil.rmtree(final_dir, ignore_errors=True)

    try:
        with build_lock(repo_key, timeout_seconds=settings.rag_build_lock_timeout_seconds):
            logger.info("%s building snapshot for %s -> %s", RAG_LOG, repo_path.name, final_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            model = _get_model()
            client = chromadb.PersistentClient(path=str(staging_dir))
            collection = client.get_or_create_collection(
                COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )

            texts: list[str] = []
            metadatas: list[dict] = []
            ids: list[str] = []
            files_scanned = 0
            chunks_indexed = 0
            for fpath in repo_path.rglob("*"):
                if not fpath.is_file():
                    continue
                rel = fpath.relative_to(repo_path)
                if not should_index_path(rel):
                    continue
                files_scanned += 1
                if files_scanned % 50 == 0:
                    logger.info("%s scanned %d files, %d chunks so far", RAG_LOG, files_scanned, chunks_indexed + len(texts))
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    logger.debug("build_index: skipped %s: %s", rel, exc)
                    continue
                file_hash = _sha1_text(content)
                language = _language_for_path(rel)
                for chunk in chunk_file(rel.as_posix(), content):
                    chunk_id = f"{rel.as_posix()}:{chunk.start_line}"
                    texts.append(chunk.text)
                    metadatas.append(
                        {
                            "file_path": rel.as_posix(),
                            "language": language,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "symbol_name": chunk.symbol_name or "",
                            "source_file_hash": file_hash,
                            "chunk_hash": _sha1_text(chunk.text),
                        }
                    )
                    ids.append(chunk_id)
                    if len(texts) >= batch_size:
                        chunks_indexed += _flush_batch(collection, model, texts, metadatas, ids)

            chunks_indexed += _flush_batch(collection, model, texts, metadatas, ids)
            logger.info("%s chunking/indexing done — %d files, %d chunks (%.1fs)", RAG_LOG, files_scanned, chunks_indexed, time.monotonic() - t0)

            meta = {
                "snapshot_version": version,
                "source_commit": head,
                "repo_key": repo_key,
                "index_schema_version": INDEX_SCHEMA_VERSION,
                "embedding_model": settings.rag_embedding_model,
                "file_count": files_scanned,
                "chunk_count": chunks_indexed,
                "build_started_at": load_runtime_state(repo_key).last_build_started_at,
                "build_finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            snapshot_meta_path(staging_dir).write_text(json.dumps(meta, indent=2))

            count = collection.count()
            if count != chunks_indexed:
                raise RuntimeError(f"snapshot validation failed: expected {chunks_indexed} chunks, found {count}")

            staging_dir.replace(final_dir)
            publish_active_snapshot(
                repo_key,
                {
                    "snapshot_version": version,
                    "snapshot_dir": str(final_dir),
                    "source_commit": head,
                    "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                },
            )
            mark_snapshot_published(
                repo_key,
                repo_name=repo_key,
                repo_path=str(repo_path),
                snapshot_version=version,
                snapshot_dir=final_dir,
                source_commit=head,
            )
            state = validate_runtime_state(repo_path)
            save_runtime_state(repo_key, state)
            logger.info("%s published snapshot %s for %s (%d chunks, %.1fs)", RAG_LOG, version, repo_path.name, chunks_indexed, time.monotonic() - t0)
            return final_dir
    except Exception as exc:
        cleanup_staging_dir(staging_dir)
        mark_build_failed(repo_key, str(exc))
        validate_runtime_state(repo_path)
        logger.exception("%s snapshot build failed for %s: %s", RAG_LOG, repo_path.name, exc)
        raise


def build_index(repo_path: Path) -> Path:
    """Build and publish a versioned ChromaDB snapshot. Retries with smaller batch on compaction error."""
    try:
        return _build_index_inner(repo_path, batch_size=BATCH_SIZE)
    except Exception as exc:
        if _is_chromadb_compaction_error(exc):
            logger.warning(
                "%s ChromaDB compaction error (known bug with large datasets). Retrying with smaller batch.",
                RAG_LOG,
            )
            try:
                return _build_index_inner(repo_path, batch_size=64)
            except Exception as retry_exc:
                hint = COMPACTION_ERROR_HINT if _is_chromadb_compaction_error(retry_exc) else ""
                raise type(retry_exc)(str(retry_exc) + hint) from retry_exc
        raise
