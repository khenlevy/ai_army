"""Tests for RAG runtime state and query fallback behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_army.rag.runtime_state import RepoCapabilities, RepoRuntimeState, validate_runtime_state
from ai_army.rag.search import query_codebase


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_validate_runtime_state_uses_lexical_fallback(monkeypatch, tmp_path):
    """Fallback mode should still mark search/code readiness for a local repo."""
    repo_path = tmp_path / "repo"
    _init_git_repo(repo_path)

    monkeypatch.setattr("ai_army.rag.runtime_state.settings.rag_use_grep_fallback", True)
    monkeypatch.setattr("ai_army.rag.runtime_state.settings.repo_workspace", str(tmp_path / "workspace"))
    monkeypatch.setattr("ai_army.rag.runtime_state.lexical_fallback_available", lambda: True)

    state = validate_runtime_state(repo_path)

    assert state.retrieval_mode == "lexical_fallback"
    assert state.capabilities.search_ready is True
    assert state.capabilities.code_ops_ready is True
    assert state.agent_state == "agents_degraded_search"


def test_query_codebase_returns_fallback_results(monkeypatch, tmp_path):
    """Query plane should return lexical results without trying to build an index."""
    repo_path = tmp_path / "repo"
    _init_git_repo(repo_path)

    state = RepoRuntimeState(
        repo_key=repo_path.name,
        retrieval_mode="lexical_fallback",
        index_state="index_degraded",
        capabilities=RepoCapabilities(search_ready=True, code_ops_ready=True),
    )
    monkeypatch.setattr("ai_army.rag.search.validate_runtime_state", lambda _: state)
    monkeypatch.setattr("ai_army.rag.search._grep_search", lambda *_args, **_kwargs: [{"file_path": "README.md", "start_line": 1, "end_line": 1, "snippet": "hello"}])

    response = query_codebase(repo_path, "hello", top_k=3)

    assert response.retrieval_mode == "lexical_fallback"
    assert response.results[0]["file_path"] == "README.md"
