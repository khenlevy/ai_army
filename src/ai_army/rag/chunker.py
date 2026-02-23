"""Chunk code by logical units (function, class) for RAG indexing."""

import re
from dataclasses import dataclass
from pathlib import Path

# Dir names to skip when walking
SKIP_DIRS = frozenset(
    {"node_modules", "__pycache__", ".git", "build", "dist", ".next", "venv", ".venv"}
)
# File patterns to skip
SKIP_EXTENSIONS = frozenset(
    {".min.js", ".min.css", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
)
# Regex for logical boundaries (Python, JS/TS)
BOUNDARY_PATTERN = re.compile(
    r"^(\s*)(def |class |async def |function |export function |export default function )"
)


@dataclass
class Chunk:
    """A code chunk with location metadata."""

    text: str
    start_line: int
    end_line: int
    symbol_name: str | None = None


def should_index_path(file_path: Path) -> bool:
    """Return True if the file should be indexed."""
    path_str = file_path.as_posix()
    if any(part in SKIP_DIRS for part in file_path.parts):
        return False
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    if path_str.endswith(".min.js") or path_str.endswith(".min.css"):
        return False
    return True


def chunk_file(relative_path: str, content: str) -> list[Chunk]:
    """Split file into chunks by def/class/function boundaries.

    Returns list of Chunk with text, start_line, end_line, symbol_name.
    """
    lines = content.splitlines()
    if not lines:
        return []

    # Find boundaries
    boundaries: list[tuple[int, str | None]] = [(0, None)]
    for i, line in enumerate(lines):
        m = BOUNDARY_PATTERN.match(line)
        if m:
            symbol = m.group(2).strip()
            name_match = re.search(r"(def|class|function)\s+(\w+)", line)
            symbol_name = name_match.group(2) if name_match else symbol
            boundaries.append((i, symbol_name))

    chunks: list[Chunk] = []
    for idx, (start, symbol_name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines) - 1
        if end < start:
            continue
        text = "\n".join(lines[start : end + 1])
        if not text.strip():
            continue
        chunks.append(
            Chunk(
                text=text,
                start_line=start + 1,
                end_line=end + 1,
                symbol_name=symbol_name,
            )
        )

    # Fallback when no def/class found: whole file if small, else by ~80 lines
    if len(boundaries) == 1 and len(lines) > 1:
        if len(lines) < 150:
            chunks = [
                Chunk(text=content, start_line=1, end_line=len(lines), symbol_name=None)
            ]
        else:
            chunk_size = 80
            chunks = []
            for i in range(0, len(lines), chunk_size):
                block = lines[i : i + chunk_size]
                chunks.append(
                    Chunk(
                        text="\n".join(block),
                        start_line=i + 1,
                        end_line=min(i + chunk_size, len(lines)),
                        symbol_name=None,
                    )
                )

    return chunks
