"""Tests for RAG chunker (no sentence-transformers required)."""

from pathlib import Path

import pytest

from ai_army.rag.chunker import Chunk, chunk_file, should_index_path


def test_chunk_file_python():
    """Chunk Python file by def/class (each function/method is a chunk)."""
    content = '''def foo():
    return 1

class Bar:
    def baz(self):
        pass
'''
    chunks = chunk_file("test.py", content)
    assert len(chunks) == 3  # foo, Bar, baz (nested method)
    assert chunks[0].symbol_name == "foo"
    assert chunks[0].start_line == 1
    assert chunks[1].symbol_name == "Bar"
    assert chunks[1].start_line == 4
    assert chunks[2].symbol_name == "baz"
    assert chunks[2].start_line == 5


def test_chunk_file_small_no_boundaries():
    """Small file without def/class becomes one chunk."""
    content = "x = 1\ny = 2\n"
    chunks = chunk_file("config.py", content)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2


def test_should_index_path():
    """Filter out node_modules, __pycache__, etc."""
    assert should_index_path(Path("src/foo.py")) is True
    assert should_index_path(Path("README.md")) is True
    assert should_index_path(Path("node_modules/x")) is False
    assert should_index_path(Path("foo/__pycache__/x.pyc")) is False
    assert should_index_path(Path("dist/out.js")) is False
