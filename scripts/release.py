#!/usr/bin/env python3
"""Release script: create git tag and optionally deploy to ai-army-droplet.

Usage:
    python scripts/release.py              # Create tag only
    python scripts/release.py --deploy     # Create tag and deploy to droplet
    python scripts/release.py --dry-run    # Show what would run, no changes
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SSH_HOST = "ai-army-droplet"
# Default app path on droplet (override with RELEASE_APP_PATH env)
DEFAULT_APP_PATH = "~/ai_army"


def get_current_version() -> str:
    """Read version from pyproject.toml."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if not match:
        raise RuntimeError("Could not find version in pyproject.toml")
    return match.group(1)


def run(cmd: list[str], dry_run: bool = False) -> int:
    """Run command. If dry_run, print and return 0."""
    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return 0
    return subprocess.run(cmd).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Release AI-Army")
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to droplet after creating tag",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show commands without executing",
    )
    args = parser.parse_args()

    version = get_current_version()
    tag = f"v{version}"

    if args.dry_run:
        print("Dry run - no changes will be made\n")

    # 1. Create git tag
    print(f"Creating tag {tag}...")
    rc = run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], dry_run=args.dry_run)
    if rc != 0:
        return rc
    if not args.dry_run:
        print(f"Created tag {tag}")

    # 2. Deploy to droplet (optional)
    if args.deploy:
        app_path = os.getenv("RELEASE_APP_PATH", DEFAULT_APP_PATH)
        print(f"\nDeploying to {SSH_HOST}...")
        # git pull, poetry install, then copy .env.production -> .env for prod
        remote_cmd = (
            f"cd {app_path} && git pull && poetry install --no-interaction "
            "&& cp .env.production .env"
        )
        deploy_cmd = ["ssh", SSH_HOST, remote_cmd]
        rc = run(deploy_cmd, dry_run=args.dry_run)
        if rc != 0:
            return rc
        if not args.dry_run:
            print(f"Deployed to {SSH_HOST}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
