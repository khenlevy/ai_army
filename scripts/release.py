#!/usr/bin/env python3
"""Release script: create git tag and optionally deploy to ai-army-droplet.

Deploy ensures prerequisites (Docker, repo) via scripts/setup-droplet.sh, then
builds and runs the app in Docker.

Usage:
    python scripts/release.py              # Create tag only
    python scripts/release.py --deploy     # Create tag, ensure prerequisites, deploy
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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def get_current_version() -> str:
    """Read version from pyproject.toml."""
    pyproject = REPO_ROOT / "pyproject.toml"
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


def get_origin_url() -> str:
    """Get git remote origin URL for clone on droplet (optional)."""
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def ensure_prerequisites(app_path: str, dry_run: bool) -> int:
    """Run setup-droplet.sh on the remote to install Docker and ensure repo. Part of deploy."""
    setup_script = (SCRIPT_DIR / "setup-droplet.sh").read_text()
    env = f"RELEASE_APP_PATH={app_path}"
    origin = get_origin_url()
    if origin:
        env += f" GIT_REPO_URL={origin}"
    remote_cmd = f"{env} bash -s"
    cmd = ["ssh", SSH_HOST, remote_cmd]
    if dry_run:
        print(f"  [dry-run] ensure prerequisites (Docker, repo) via setup-droplet.sh")
        return 0
    proc = subprocess.Popen(
        ["ssh", SSH_HOST, remote_cmd],
        stdin=subprocess.PIPE,
        text=True,
    )
    proc.stdin.write(setup_script)
    proc.stdin.close()
    return proc.wait()


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

    # 2. Deploy to droplet (optional) – ensure prerequisites, then Docker build & run
    if args.deploy:
        app_path = os.getenv("RELEASE_APP_PATH", DEFAULT_APP_PATH)
        print(f"\nEnsuring prerequisites on {SSH_HOST}...")
        rc = ensure_prerequisites(app_path, args.dry_run)
        if rc != 0:
            return rc
        print(f"Deploying to {SSH_HOST} (Docker)...")
        # Prerequisites are met; cd app, pull, build, replace container
        remote_cmd = (
            f"cd {app_path} && "
            "test -f .env.production || (echo 'Missing .env.production on droplet' && exit 1) && "
            "git pull && "
            "sudo docker build -t ai-army:latest . && "
            "sudo docker stop ai-army 2>/dev/null; sudo docker rm ai-army 2>/dev/null; "
            'sudo docker run -d --name ai-army --restart unless-stopped '
            "-v $(pwd)/.env.production:/app/.env.production ai-army:latest"
        )
        deploy_cmd = ["ssh", SSH_HOST, remote_cmd]
        rc = run(deploy_cmd, dry_run=args.dry_run)
        if rc != 0:
            return rc
        if not args.dry_run:
            print(f"Deployed to {SSH_HOST}. View logs: ssh {SSH_HOST} 'sudo docker logs -f ai-army'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
