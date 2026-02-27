"""Search codebase tool - semantic search over indexed repo."""

import logging
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.config.settings import GitHubRepoConfig
from ai_army.rag.search import search
from ai_army.tools.github_helpers import _get_repo_from_config

logger = logging.getLogger(__name__)


def _repo_root(override: str | None) -> Path | None:
    """Resolve repo root. Return None if not set or not a git repo."""
    if not override or not override.strip():
        return None
    p = Path(override).expanduser().resolve()
    if not (p / ".git").exists():
        return None
    return p


class SearchCodebaseInput(BaseModel):
    """Input for SearchCodebaseTool."""

    query: str = Field(
        default="",
        description="Search query (e.g. issue title, keywords). Leave empty if using issue_number.",
    )
    issue_number: int | None = Field(
        default=None,
        description="GitHub issue number. When set, uses issue title+body as query if query is empty.",
    )
    max_results: int = Field(default=8, ge=1, le=20, description="Max number of results to return")


class SearchCodebaseTool(BaseTool):
    """Search the codebase by semantic similarity. Use with issue number or a text query."""

    name: str = "Search Codebase"
    description: str = (
        "RAG semantic search over the codebase. Uses the configured embedding model to find code relevant to a query. "
        "Use the current issue number to search by issue title and body, or pass a short query (e.g. keywords from the issue). "
        "Returns file paths and snippets. Use Read File on those paths to implement changes."
    )
    args_schema: Type[BaseModel] = SearchCodebaseInput

    def __init__(
        self,
        repo_path: str | None = None,
        repo_config: GitHubRepoConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._repo_path = repo_path
        self._repo_config = repo_config

    def _run(
        self,
        query: str = "",
        issue_number: int | None = None,
        max_results: int = 8,
    ) -> str:
        root = _repo_root(self._repo_path)
        if not root:
            logger.warning("SearchCodebaseTool: repo path not configured")
            return "Repo path not configured. Cannot search codebase."

        search_query = query.strip()
        if not search_query and issue_number and self._repo_config:
            try:
                repo = _get_repo_from_config(self._repo_config)
                issue = repo.get_issue(issue_number)
                search_query = f"{issue.title}\n{issue.body or ''}".strip()
            except Exception as e:
                logger.warning("Failed to fetch issue #%s: %s", issue_number, e)
                return f"Could not fetch issue #{issue_number}. Use a text query instead."

        if not search_query:
            logger.warning("SearchCodebaseTool: no query provided")
            return "Provide a query or issue_number to search."

        logger.info("SearchCodebaseTool: searching repo=%s issue=%s query_len=%d", root.name, issue_number, len(search_query))
        results = search(root, search_query, top_k=max_results)
        if not results:
            logger.info("SearchCodebaseTool: no results for query (len=%d)", len(search_query))
            return "No relevant code found."

        logger.info("SearchCodebaseTool: found %d results for query", len(results))
        lines = []
        for r in results:
            fp = r.get("file_path", "")
            start = r.get("start_line", 0)
            end = r.get("end_line", 0)
            snippet = r.get("snippet", "")
            lines.append(f"{fp} (L{start}-{end}):\n{snippet}\n")
        return "\n---\n".join(lines)
