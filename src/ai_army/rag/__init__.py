"""RAG module for codebase semantic search."""

from ai_army.rag.chunker import Chunk, chunk_file, should_index_path

__all__ = [
    "Chunk",
    "chunk_file",
    "should_index_path",
    "build_index",
    "CodebaseRetriever",
    "search",
]


def __getattr__(name: str):
    """Lazy import for heavy deps (sentence-transformers, chromadb)."""
    if name == "build_index":
        from ai_army.rag.indexer import build_index
        return build_index
    if name == "search":
        from ai_army.rag.search import search
        return search
    if name == "CodebaseRetriever":
        from ai_army.rag.retriever import CodebaseRetriever
        return CodebaseRetriever
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
