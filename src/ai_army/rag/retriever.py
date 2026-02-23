"""LangChain BaseRetriever wrapping codebase semantic search."""

import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ai_army.rag.search import search

logger = logging.getLogger(__name__)


class CodebaseRetriever(BaseRetriever):
    """LangChain retriever that wraps rag.search() for codebase semantic search.

    Returns Document objects with page_content (snippet) and metadata
    (file_path, start_line, end_line). Compatible with RetrievalQA,
    create_retrieval_chain, etc.
    """

    repo_path: str
    """Path to the git repository to search."""

    top_k: int = 8
    """Maximum number of documents to return."""

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        """Retrieve documents relevant to the query."""
        repo_path = Path(self.repo_path).resolve()
        if not (repo_path / ".git").exists():
            logger.warning("CodebaseRetriever: %s is not a git repo", self.repo_path)
        results = search(
            repo_path,
            query,
            top_k=self.top_k,
        )
        logger.info("CodebaseRetriever: retrieved %d documents for query", len(results))
        docs: list[Document] = []
        for r in results:
            metadata: dict[str, Any] = {
                "file_path": r.get("file_path", ""),
                "start_line": r.get("start_line", 0),
                "end_line": r.get("end_line", 0),
            }
            docs.append(
                Document(
                    page_content=r.get("snippet", ""),
                    metadata=metadata,
                )
            )
        return docs
