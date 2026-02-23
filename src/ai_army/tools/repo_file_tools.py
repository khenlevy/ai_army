"""Tools for dev agents to read, write, and explore files in the cloned repo.

All paths are relative to the repo root. Scoped to repo_path to prevent escape.
"""

import logging
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _repo_root(override: str | None) -> Path | None:
    """Resolve repo root. Return None if not set or not a git repo."""
    if not override or not override.strip():
        return None
    p = Path(override).expanduser().resolve()
    if not (p / ".git").exists():
        return None
    return p


def _resolve_safe(repo_root: Path, relative_path: str) -> Path | None:
    """Resolve path under repo root. Return None if path escapes (e.g. ..)."""
    if not relative_path or relative_path.strip() == "":
        return repo_root
    path = (repo_root / relative_path.strip().lstrip("/")).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError:
        return None
    return path


# --- ListDirTool ---


class ListDirInput(BaseModel):
    """Input for ListDirTool."""

    path: str = Field(
        default=".",
        description="Directory path relative to repo root (e.g. 'src', 'src/components'). Use '.' for repo root.",
    )
    max_entries: int = Field(default=100, ge=1, le=500, description="Max files/dirs to return (avoid huge listings)")


class ListDirTool(BaseTool):
    """List files and subdirectories in a directory. Use to explore repo structure."""

    name: str = "List Directory"
    description: str = (
        "List contents of a directory in the repo. Path is relative to repo root (e.g. 'src', '.'). "
        "Use repeatedly to explore the codebase structure before implementing."
    )
    args_schema: Type[BaseModel] = ListDirInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path = repo_path

    def _run(self, path: str = ".", max_entries: int = 100) -> str:
        root = _repo_root(self._repo_path)
        if not root:
            logger.warning("ListDirTool: repo path not configured")
            return "Repo path not configured. Cannot list directory."
        resolved = _resolve_safe(root, path)
        if not resolved:
            logger.warning("ListDirTool: invalid or unsafe path: %s", path)
            return "Invalid or unsafe path (cannot escape repo root)."
        if not resolved.is_dir():
            logger.warning("ListDirTool: not a directory: %s", path)
            return f"Not a directory: {path}"
        entries = []
        try:
            for i, entry in enumerate(sorted(resolved.iterdir())):
                if i >= max_entries:
                    entries.append(f"... and more (truncated at {max_entries})")
                    break
                name = entry.name
                if entry.is_dir():
                    entries.append(f"{name}/")
                else:
                    entries.append(name)
            logger.info("ListDirTool: listed %s (%d entries)", path, len(entries))
        except OSError as e:
            logger.warning("ListDirTool: error listing %s: %s", path, e)
            return f"Error listing directory: {e}"
        return "\n".join(entries) if entries else "(empty)"


# --- RepoStructureTool ---


class RepoStructureInput(BaseModel):
    """Input for RepoStructureTool."""

    max_depth: int = Field(default=2, ge=1, le=4, description="How many directory levels to show (1 = root only)")


class RepoStructureTool(BaseTool):
    """Get a quick overview of the repo directory structure. Use first to understand the codebase."""

    name: str = "Repo Structure"
    description: str = (
        "Get a tree overview of the repo (files and folders up to a few levels). "
        "Use this first to understand the project layout before reading files and implementing."
    )
    args_schema: Type[BaseModel] = RepoStructureInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path = repo_path

    def _run(self, max_depth: int = 2) -> str:
        root = _repo_root(self._repo_path)
        if not root:
            logger.warning("RepoStructureTool: repo path not configured")
            return "Repo path not configured. Cannot get structure."
        lines = []

        def walk(dir_path: Path, prefix: str, depth: int) -> None:
            if depth <= 0:
                return
            try:
                entries = sorted(dir_path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
            except OSError:
                return
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                branch = "└── " if is_last else "├── "
                lines.append(prefix + branch + entry.name + ("/" if entry.is_dir() else ""))
                if entry.is_dir() and depth > 1:
                    extension = "    " if is_last else "│   "
                    walk(entry, prefix + extension, depth - 1)
        walk(root, "", max_depth)
        return "\n".join(lines) if lines else "(empty repo)"


# --- ReadFileTool ---


class ReadFileInput(BaseModel):
    """Input for ReadFileTool."""

    path: str = Field(..., description="File path relative to repo root (e.g. 'src/App.tsx', 'README.md')")
    max_lines: int = Field(default=500, ge=1, le=2000, description="Max lines to return (truncate long files)")


class ReadFileTool(BaseTool):
    """Read file contents from the repo. Use to understand code before editing."""

    name: str = "Read File"
    description: str = (
        "Read the contents of a file in the repo. Path is relative to repo root (e.g. 'README.md', 'src/App.tsx'). "
        "Use to understand the codebase and then implement changes. Long files are truncated; check max_lines."
    )
    args_schema: Type[BaseModel] = ReadFileInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path = repo_path

    def _run(self, path: str, max_lines: int = 500) -> str:
        root = _repo_root(self._repo_path)
        if not root:
            logger.warning("ReadFileTool: repo path not configured")
            return "Repo path not configured. Cannot read file."
        resolved = _resolve_safe(root, path)
        if not resolved:
            logger.warning("ReadFileTool: invalid or unsafe path: %s", path)
            return "Invalid or unsafe path (cannot escape repo root)."
        if not resolved.is_file():
            logger.warning("ReadFileTool: not a file or not found: %s", path)
            return f"Not a file or not found: {path}"
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            truncated = len(lines) > max_lines
            logger.info("ReadFileTool: read %s (%d lines%s)", path, len(lines), ", truncated" if truncated else "")
        except OSError as e:
            logger.warning("ReadFileTool: error reading %s: %s", path, e)
            return f"Error reading file: {e}"
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n\n... truncated ({len(lines) - max_lines} more lines)"
        return text


# --- WriteFileTool ---


class WriteFileInput(BaseModel):
    """Input for WriteFileTool."""

    path: str = Field(..., description="File path relative to repo root (e.g. 'src/NewComponent.tsx')")
    content: str = Field(..., description="Full new content of the file")
    create_dirs: bool = Field(default=True, description="Create parent directories if they do not exist")


class WriteFileTool(BaseTool):
    """Write or overwrite a file in the repo. Use after reading and understanding existing code."""

    name: str = "Write File"
    description: str = (
        "Write or overwrite a file in the repo. Path is relative to repo root. "
        "Use after reading relevant files to implement your changes. You can make multiple edits and commits."
    )
    args_schema: Type[BaseModel] = WriteFileInput

    def __init__(self, repo_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_path = repo_path

    def _run(self, path: str, content: str, create_dirs: bool = True) -> str:
        root = _repo_root(self._repo_path)
        if not root:
            logger.warning("WriteFileTool: repo path not configured")
            return "Repo path not configured. Cannot write file."
        resolved = _resolve_safe(root, path)
        if not resolved:
            logger.warning("WriteFileTool: invalid or unsafe path: %s", path)
            return "Invalid or unsafe path (cannot escape repo root)."
        try:
            if create_dirs:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            logger.info("WriteFileTool: wrote %s (%d chars)", path, len(content))
        except OSError as e:
            logger.warning("WriteFileTool: error writing %s: %s", path, e)
            return f"Error writing file: {e}"
        return f"Wrote {path} ({len(content)} chars)"
