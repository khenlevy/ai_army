#!/usr/bin/env python3
"""Release script: create git tag for current version.

Release and deploy workflows expect .env.production for production configuration.
The deploy script (scripts/deploy) loads .env.production explicitly.

Usage:
    python scripts/release.py
"""

import re
import subprocess
import sys
from pathlib import Path


def get_current_version() -> str:
    """Read version from pyproject.toml."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if not match:
        raise RuntimeError("Could not find version in pyproject.toml")
    return match.group(1)


def main() -> int:
    version = get_current_version()
    tag = f"v{version}"

    subprocess.run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], check=True)
    print(f"Created tag {tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
