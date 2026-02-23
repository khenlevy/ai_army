#!/usr/bin/env python3
"""Release script: deploy current code to ai-army-droplet.

Copies .env.production, ensures prerequisites (Docker, repo), then builds and runs the app.

Usage:
    python scripts/release.py       # Deploy
    python scripts/release.py --dry-run   # Show what would run
"""

import os
import subprocess
import sys
from pathlib import Path

SSH_HOST = "ai-army-droplet"
DEFAULT_APP_PATH = "~/ai_army"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def run(cmd: list[str], dry_run: bool = False) -> int:
    """Run command. If dry_run, print and return 0."""
    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return 0
    return subprocess.run(cmd).returncode


def get_origin_url() -> str:
    """Get git remote origin URL for clone on droplet."""
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    url = r.stdout.strip() if r.returncode == 0 else ""
    if not url:
        return ""
    if url.startswith("git@github.com:"):
        return url.replace("git@github.com:", "https://github.com/", 1)
    if url.startswith("ssh://git@github.com/"):
        return url.replace("ssh://git@github.com/", "https://github.com/", 1)
    return url


def ensure_prerequisites(app_path: str, dry_run: bool) -> int:
    """Run setup-droplet.sh on the remote."""
    setup_script = (SCRIPT_DIR / "setup-droplet.sh").read_text()
    env = f"RELEASE_APP_PATH={app_path}"
    origin = get_origin_url()
    if origin:
        env += f" GIT_REPO_URL={origin}"
    remote_cmd = f"{env} bash -s"
    if dry_run:
        print("  [dry-run] ensure prerequisites (Docker, repo) via setup-droplet.sh")
        return 0
    proc = subprocess.Popen(
        ["ssh", SSH_HOST, remote_cmd],
        stdin=subprocess.PIPE,
        text=True,
    )
    proc.stdin.write(setup_script)
    proc.stdin.close()
    return proc.wait()


def copy_env_production(app_path: str, dry_run: bool) -> int:
    """Copy local .env.production to the droplet."""
    env_file = REPO_ROOT / ".env.production"
    if not env_file.is_file():
        print("Error: .env.production not found. Create it from .env.example and run again.")
        return 1
    remote_dest = f"{SSH_HOST}:{app_path}/.env.production"
    cmd = ["scp", str(env_file), remote_dest]
    if dry_run:
        print(f"  [dry-run] scp .env.production to {remote_dest}")
        return 0
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Release AI-Army (deploy to droplet)")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    app_path = os.getenv("RELEASE_APP_PATH", DEFAULT_APP_PATH)

    if args.dry_run:
        print("Dry run - no changes will be made\n")

    print(f"Copying .env.production to {SSH_HOST}...")
    rc = copy_env_production(app_path, args.dry_run)
    if rc != 0:
        return rc

    print(f"Ensuring prerequisites on {SSH_HOST}...")
    rc = ensure_prerequisites(app_path, args.dry_run)
    if rc != 0:
        return rc

    print(f"Deploying to {SSH_HOST} (Docker)...")
    remote_cmd = (
        f"cd {app_path} && "
        "git pull && "
        "sudo docker builder prune -af 2>/dev/null || true && "
        "sudo docker build -t ai-army:latest . && "
        "(sudo docker stop ai-army 2>/dev/null || true) && "
        "(sudo docker rm ai-army 2>/dev/null || true) && "
        'sudo docker run -d --name ai-army --restart unless-stopped '
        "--env-file .env.production "
        "-v $(pwd)/.env.production:/app/.env.production ai-army:latest"
    )
    rc = run(["ssh", SSH_HOST, remote_cmd], dry_run=args.dry_run)
    if rc != 0:
        return rc

    if not args.dry_run:
        print(f"Deployed to {SSH_HOST}.")
        import time
        time.sleep(5)
        print("\n--- Recent logs ---\n")
        run(["ssh", SSH_HOST, "sudo docker logs ai-army --tail 50"], dry_run=False)
        print("\n---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
