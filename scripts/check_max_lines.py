#!/usr/bin/env python3
"""Check that no Python file exceeds MAX_LINES. Exit 1 if any file is over the limit."""

import sys
from pathlib import Path

MAX_LINES = 250
ROOTS = ["src", "scripts"]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[tuple[Path, int]] = []
    for root in ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts or path.name.startswith("."):
                continue
            try:
                line_count = len(path.read_text().splitlines())
            except OSError:
                continue
            if line_count > MAX_LINES:
                violations.append((path.relative_to(repo_root), line_count))

    if not violations:
        return 0
    print(f"Max lines per file is {MAX_LINES}. Files over the limit:\n", file=sys.stderr)
    for path, count in sorted(violations, key=lambda x: -x[1]):
        print(f"  {path}: {count} lines", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
