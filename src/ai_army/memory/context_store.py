"""Simple context store for cross-crew memory.

Stores summaries from each crew run so the next crew can see what happened.
Persists to a JSON file for cross-run continuity.
"""

import json
import logging
from pathlib import Path

from ai_army.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_FILE = ".ai_army_context.json"


def _context_path() -> Path:
    """Path to the context file."""
    raw = settings.repo_workspace.strip()
    if raw:
        base = Path(raw).expanduser().resolve()
    else:
        base = Path.cwd().resolve() / ".ai_army_workspace"
    base.mkdir(parents=True, exist_ok=True)
    return base / DEFAULT_CONTEXT_FILE


class ContextStore:
    """Stores crew run summaries for handoff to the next crew.

    Keys: product, team_lead, dev, qa
    Values: summary strings from each crew's output.
    """

    def __init__(self, file_path: Path | str | None = None):
        self._path = Path(file_path) if file_path else _context_path()
        self._data: dict[str, str] = {}

    def load(self) -> None:
        """Load context from file."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
                logger.info("ContextStore: loaded context from %s (%d crews)", self._path, len(self._data))
            except Exception as e:
                logger.warning("ContextStore: could not load from %s: %s", self._path, e)
                self._data = {}
        else:
            logger.debug("ContextStore: no context file at %s, starting fresh", self._path)
            self._data = {}

    def save(self) -> None:
        """Persist context to file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
            logger.debug("ContextStore: saved context to %s", self._path)
        except Exception as e:
            logger.warning("ContextStore: could not save to %s: %s", self._path, e)

    def add(self, crew_name: str, summary: str) -> None:
        """Add or update summary for a crew."""
        self._data[crew_name] = summary
        self.save()
        logger.info("ContextStore: added/updated context for crew=%s (summary len=%d)", crew_name, len(summary))

    def get(self, crew_name: str) -> str:
        """Get summary for a crew."""
        return self._data.get(crew_name, "")

    def get_summary(self, exclude: str | None = None) -> str:
        """Get aggregated summary for handoff to the next crew.

        exclude: crew name to exclude (e.g. current crew).
        """
        parts = []
        for name in ("product", "team_lead", "dev", "qa"):
            if name == exclude:
                continue
            val = self._data.get(name, "").strip()
            if val:
                parts.append(f"[{name}]\n{val}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def clear(self) -> None:
        """Clear all context."""
        self._data = {}
        self.save()


# Module-level default store for CLI use
_default_store: ContextStore | None = None


def get_context_store() -> ContextStore:
    """Get the default context store (lazy init)."""
    global _default_store
    if _default_store is None:
        _default_store = ContextStore()
        _default_store.load()
    return _default_store
