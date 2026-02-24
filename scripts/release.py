#!/usr/bin/env python3
"""Release script: build locally. Images stay local (no GHCR push, no remote deploy).

Flow: version bump -> git commit/push -> docker build.

Usage:
    python scripts/release.py           # Build
    python scripts/release.py --dry-run # Show what would run
    python scripts/release.py --no-bump # Skip version bump (retry after build failure)
"""

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

SSH_HOST = "ai-army-droplet"
IMAGE = "ghcr.io/khenlevy/ai-army"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def log(msg: str, step: str = "", elapsed_sec: float | None = None) -> None:
    """Print with timestamp; flush so output appears immediately."""
    ts = time.strftime("%H:%M:%S", time.localtime())
    prefix = f"[{ts}] " + (f"[{step}] " if step else "")
    suffix = f" (+{elapsed_sec:.1f}s)" if elapsed_sec is not None else ""
    print(prefix + msg + suffix, flush=True)


def ensure_docker_running(dry_run: bool = False) -> int:
    """Ensure Docker daemon is running. Start Docker Desktop on macOS if needed."""
    r = subprocess.run(["docker", "info"], capture_output=True)
    if r.returncode == 0:
        return 0
    if dry_run:
        print("  [dry-run] ensure Docker is running")
        return 0
    if platform.system() == "Darwin":
        print("Docker not running. Starting Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"], check=True)
        for i in range(60):
            time.sleep(2)
            r = subprocess.run(["docker", "info"], capture_output=True)
            if r.returncode == 0:
                print("Docker is ready.")
                return 0
            print(f"  Waiting for Docker... ({i * 2}s)")
        print("Error: Docker did not start within 2 minutes.")
        return 1
    print("Error: Docker is not running. Start Docker Desktop and try again.")
    return 1


def run(cmd: list[str], dry_run: bool = False, cwd: Path | None = None, env: dict | None = None) -> int:
    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return 0
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd or REPO_ROOT, env=full_env).returncode


def docker_build_with_fallback(version: str, dry_run: bool) -> int:
    """Build with BuildKit; on I/O errors retry then fallback to DOCKER_BUILDKIT=0."""
    build_cmd = ["docker", "build", "-t", f"{IMAGE}:latest", "-t", f"{IMAGE}:{version}", "."]
    for use_buildkit in [True, False]:
        env = {} if use_buildkit else {"DOCKER_BUILDKIT": "0"}
        if not use_buildkit:
            log("Trying legacy builder (DOCKER_BUILDKIT=0)...")
        if dry_run:
            print(f"  [dry-run] {' '.join(build_cmd)}")
            return 0
        # Stream output to terminal (no capture_output)
        rc = run(build_cmd, dry_run=False, env=env)
        if rc == 0:
            return 0
        if use_buildkit:
            log("Build failed, retrying in 5s...")
            time.sleep(5)
            rc = run(build_cmd, dry_run=False, env=env)
            if rc == 0:
                return 0
            log("Retry failed, trying legacy builder...")
        else:
            return rc
    return 1


def get_version() -> str:
    r = subprocess.run(
        ["poetry", "version", "-s"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "0.0.0"


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Release AI-Army (build local, images stay local)")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    parser.add_argument("--no-bump", action="store_true", help="Skip version bump (retry after build failure)")
    args = parser.parse_args()

    script_start = time.monotonic()
    log("Starting release script", "init")

    def elapsed() -> float:
        return time.monotonic() - script_start

    if args.dry_run:
        log("Dry run - no changes will be made\n", "init")

    # 1. Version bump (unless --no-bump)
    log("Step 1/3: Version bump", "1", elapsed())
    if args.no_bump:
        log("Skipping version bump (--no-bump)")
        version = get_version()
    else:
        log("Bumping version...")
        rc = run(["poetry", "version", "patch"], dry_run=args.dry_run)
        if rc != 0:
            return rc
        version = get_version()
    if args.dry_run:
        version = "0.1.4"
    log(f"Version: {version}", elapsed_sec=elapsed())

    # 2. Git commit and push (skip if --no-bump)
    log("Step 2/3: Git commit/push", "2", elapsed())
    if args.no_bump:
        log("Skipping git commit/push (--no-bump)")
    else:
        log("Committing and pushing...")
        if not args.dry_run:
            rc = subprocess.run(["git", "add", "pyproject.toml"], cwd=REPO_ROOT).returncode
            if rc != 0:
                return rc
            rc = subprocess.run(
                ["git", "commit", "-m", f"chore: bump version to {version}"],
                cwd=REPO_ROOT,
            ).returncode
            if rc != 0:
                return rc
            rc = subprocess.run(["git", "push"], cwd=REPO_ROOT).returncode
            if rc != 0:
                return rc
        else:
            print(f"  [dry-run] git add pyproject.toml && git commit -m 'chore: bump version to {version}' && git push")

    # 3. Build locally
    log("Step 3/3: Building Docker image (2-5 min)", "3", elapsed())
    rc = docker_build_with_fallback(version, args.dry_run)
    if rc != 0:
        return rc

    log(f"Done. Image: {IMAGE}:latest, {IMAGE}:{version}", elapsed_sec=elapsed())
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
