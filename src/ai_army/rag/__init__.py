"""RAG – codebase indexing and semantic search.

Indexing (indexer.build_index): Walks repo, chunks via chunker, embeds with sentence-transformers,
persists to ChromaDB in .ai_army_index/{slug}/.
Search (search.search): Ensures index exists/fresh (rebuilds if HEAD changed), embeds query, returns
top-k snippets. Used by SearchCodebaseTool for Dev crew.
"""

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
