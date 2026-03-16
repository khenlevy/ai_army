"""Tests for RAG indexer - ensure ChromaDB compaction retry does not regress."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import chromadb
import pytest

# Mock heavy deps before importing indexer (sentence_transformers not in minimal test env)
if "sentence_transformers" not in sys.modules:
    sys.modules["sentence_transformers"] = MagicMock()

from ai_army.rag.indexer import (
    COMPACTION_ERROR_HINT,
    _is_chromadb_compaction_error,
    build_index,
)


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_is_chromadb_compaction_error_returns_true_for_compaction_internal_error() -> None:
    """Regression: compaction InternalError must be recognized for retry."""
    exc = chromadb.errors.InternalError("Error in compaction: Failed to apply logs to the metadata segment")
    assert _is_chromadb_compaction_error(exc) is True


def test_is_chromadb_compaction_error_returns_false_for_other_internal_error() -> None:
    """Other InternalErrors should not trigger retry."""
    exc = chromadb.errors.InternalError("Some other error")
    assert _is_chromadb_compaction_error(exc) is False


def test_is_chromadb_compaction_error_returns_false_for_non_chromadb_errors() -> None:
    """Non-ChromaDB errors should not trigger retry."""
    assert _is_chromadb_compaction_error(ValueError("compaction")) is False
    assert _is_chromadb_compaction_error(RuntimeError("Error in compaction")) is False


def test_build_index_retries_with_smaller_batch_on_compaction_error(
    monkeypatch, tmp_path: Path
) -> None:
    """Regression: build_index must retry with batch_size=64 when compaction error occurs."""
    repo_path = tmp_path / "repo"
    _init_git_repo(repo_path)

    call_log: list[tuple[Path, int]] = []

    def fake_build_inner(repo_path: Path, batch_size: int) -> Path:
        call_log.append((repo_path, batch_size))
        if len(call_log) == 1:
            raise chromadb.errors.InternalError(
                "Error in compaction: Failed to apply logs to the metadata segment"
            )
        return tmp_path / "snapshot"

    monkeypatch.setattr("ai_army.rag.indexer._build_index_inner", fake_build_inner)
    monkeypatch.setattr("ai_army.rag.indexer.repo_slug", lambda _: "test_repo")
    monkeypatch.setattr("ai_army.rag.indexer.staging_snapshot_dir", lambda *_: tmp_path / "staging")
    monkeypatch.setattr("ai_army.rag.indexer.snapshot_dir_for_version", lambda *_: tmp_path / "final")
    monkeypatch.setattr("ai_army.rag.indexer.cleanup_staging_dir", lambda _: None)
    monkeypatch.setattr("ai_army.rag.indexer.mark_build_started", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.mark_build_failed", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.mark_snapshot_published", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.publish_active_snapshot", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.load_runtime_state", lambda _: type("S", (), {"last_build_started_at": None})())
    monkeypatch.setattr("ai_army.rag.indexer.validate_runtime_state", lambda _: None)
    monkeypatch.setattr("ai_army.rag.indexer.save_runtime_state", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.build_lock", lambda *_, **__: type("C", (), {"__enter__": lambda _: None, "__exit__": lambda *_: None})())

    result = build_index(repo_path)

    assert len(call_log) == 2
    assert call_log[0][1] == 256, "First attempt must use default batch size"
    assert call_log[1][1] == 64, "Retry must use smaller batch size (64)"
    assert result == tmp_path / "snapshot"


def test_build_index_appends_grep_fallback_hint_when_retry_also_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """Regression: when retry fails with compaction, error must include RAG_USE_GREP_FALLBACK hint."""
    repo_path = tmp_path / "repo"
    _init_git_repo(repo_path)

    compaction_error = chromadb.errors.InternalError(
        "Error in compaction: Failed to apply logs to the metadata segment"
    )

    def fake_build_inner_always_fail(_repo_path: Path, batch_size: int) -> Path:
        raise compaction_error

    monkeypatch.setattr("ai_army.rag.indexer._build_index_inner", fake_build_inner_always_fail)
    monkeypatch.setattr("ai_army.rag.indexer.repo_slug", lambda _: "test_repo")
    monkeypatch.setattr("ai_army.rag.indexer.staging_snapshot_dir", lambda *_: tmp_path / "staging")
    monkeypatch.setattr("ai_army.rag.indexer.snapshot_dir_for_version", lambda *_: tmp_path / "final")
    monkeypatch.setattr("ai_army.rag.indexer.cleanup_staging_dir", lambda _: None)
    monkeypatch.setattr("ai_army.rag.indexer.mark_build_started", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.mark_build_failed", lambda *_, **__: None)
    monkeypatch.setattr("ai_army.rag.indexer.validate_runtime_state", lambda _: None)
    monkeypatch.setattr("ai_army.rag.indexer.build_lock", lambda *_, **__: type("C", (), {"__enter__": lambda _: None, "__exit__": lambda *_: None})())

    with pytest.raises(chromadb.errors.InternalError) as exc_info:
        build_index(repo_path)

    assert COMPACTION_ERROR_HINT in str(exc_info.value)
