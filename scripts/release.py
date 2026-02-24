#!/usr/bin/env python3
"""Release script: build locally, save to tar, ship and run on production.

Flow: version bump -> git commit/push -> docker build -> save tar -> scp -> load + run on droplet.

Usage:
    python scripts/release.py           # Build and ship
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
IMAGE = "ai-army"
CONTAINER = "ai-army"
DEFAULT_APP_PATH = "~/ai_army"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DIST_DIR = REPO_ROOT / "dist"


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
        print(f"  [dry-run] {' '.join(cmd)}", flush=True)
        return 0
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        env=full_env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    ).returncode


def docker_build_with_fallback(dry_run: bool) -> int:
    """Build with BuildKit; on I/O errors retry then fallback to DOCKER_BUILDKIT=0. Tags only :latest."""
    for use_buildkit in [True, False]:
        env = {} if use_buildkit else {"DOCKER_BUILDKIT": "0"}
        # --platform linux/amd64: droplet is x86_64; Mac M1 builds arm64 by default
        build_cmd = ["docker", "build", "--platform", "linux/amd64", "-t", f"{IMAGE}:latest", "."]
        if use_buildkit:
            build_cmd.insert(2, "--progress=plain")
        if not use_buildkit:
            log("Trying legacy builder (DOCKER_BUILDKIT=0)...")
        if dry_run:
            print(f"  [dry-run] {' '.join(build_cmd)}", flush=True)
            return 0
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


def get_origin_url() -> str:
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    url = r.stdout.strip() if r.returncode == 0 else ""
    if url.startswith("git@github.com:"):
        return url.replace("git@github.com:", "https://github.com/", 1)
    if url.startswith("ssh://git@github.com/"):
        return url.replace("ssh://git@github.com/", "https://github.com/", 1)
    return url


def ensure_prerequisites(app_path: str, dry_run: bool) -> int:
    """Run setup-droplet.sh on remote (Docker, app dir, swap)."""
    setup_script = (SCRIPT_DIR / "setup-droplet.sh").read_text()
    env = f"RELEASE_APP_PATH={app_path}"
    origin = get_origin_url()
    if origin:
        env += f" GIT_REPO_URL={origin}"
    if dry_run:
        print(f"  [dry-run] ensure prerequisites via setup-droplet.sh", flush=True)
        return 0
    proc = subprocess.Popen(
        ["ssh", SSH_HOST, f"{env} bash -s"],
        stdin=subprocess.PIPE,
        text=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    proc.stdin.write(setup_script)
    proc.stdin.close()
    return proc.wait()


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

    # 1. Preserve previous latest as versioned, then bump
    log("Step 1/9: Version + retag previous", "1", elapsed())
    prev_version = get_version()
    if args.no_bump:
        log("Skipping version bump (--no-bump)")
        version = prev_version
    else:
        # Retag current latest -> prev_version before we overwrite it
        if not args.dry_run:
            r = subprocess.run(["docker", "image", "inspect", f"{IMAGE}:latest"], capture_output=True)
            if r.returncode == 0:
                run(["docker", "tag", f"{IMAGE}:latest", f"{IMAGE}:{prev_version}"])
                log(f"Retagged previous latest -> {IMAGE}:{prev_version}")
        log("Bumping version...")
        rc = run(["poetry", "version", "patch"], dry_run=args.dry_run)
        if rc != 0:
            return rc
        version = get_version()
    if args.dry_run:
        version = "0.1.4"
    log(f"Version: {version}", elapsed_sec=elapsed())

    # 2. Git commit and push (skip if --no-bump)
    log("Step 2/9: Git commit/push", "2", elapsed())
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

    # 3. Ensure Docker is running
    log("Step 3/9: Checking Docker", "3", elapsed())
    rc = ensure_docker_running(args.dry_run)
    if rc != 0:
        return rc

    # 4. Build locally (tags only :latest)
    log("Step 4/9: Building Docker image (2-5 min)", "4", elapsed())
    rc = docker_build_with_fallback(args.dry_run)
    if rc != 0:
        return rc

    # 5. Save image to tar
    log("Step 5/9: Saving image to tar", "5", elapsed())
    DIST_DIR.mkdir(exist_ok=True)
    tar_name = f"ai-army-{version}.tar"
    tar_path = DIST_DIR / tar_name
    if args.dry_run:
        print(f"  [dry-run] docker save {IMAGE}:latest -o {tar_path}", flush=True)
    else:
        log(f"Writing {tar_path} (~1GB, may take 1-2 min)...")
        rc = run(["docker", "save", f"{IMAGE}:latest", "-o", str(tar_path)])
        if rc != 0:
            return rc
        size_mb = tar_path.stat().st_size / (1024 * 1024)
        log(f"Saved {size_mb:.1f} MB", elapsed_sec=elapsed())

    app_path = os.getenv("RELEASE_APP_PATH", DEFAULT_APP_PATH)

    # 6. Ensure prerequisites on droplet (Docker, app dir)
    log("Step 6/9: Ensuring prerequisites on droplet", "6", elapsed())
    rc = ensure_prerequisites(app_path, args.dry_run)
    if rc != 0:
        return rc

    # 7. Copy tar to production
    log("Step 7/9: Copying tar to production", "7", elapsed())
    remote_tar = f"{SSH_HOST}:{app_path}/{tar_name}"
    if args.dry_run:
        print(f"  [dry-run] scp {tar_path} {remote_tar}", flush=True)
    else:
        run(["ssh", SSH_HOST, f"mkdir -p {app_path}"])
        log(f"Uploading {tar_name} to {SSH_HOST}...")
        rc = run(["scp", str(tar_path), remote_tar])
        if rc != 0:
            return rc
        log("Tar copied", elapsed_sec=elapsed())

    # 8. Copy .env.production (not in image; required at runtime)
    log("Step 8/9: Copying .env.production", "8", elapsed())
    env_file = REPO_ROOT / ".env.production"
    if not env_file.is_file():
        log("Error: .env.production not found. Create from .env.example.")
        return 1
    remote_env = f"{SSH_HOST}:{app_path}/.env.production"
    if args.dry_run:
        print(f"  [dry-run] scp .env.production {remote_env}", flush=True)
    else:
        rc = run(["scp", str(env_file), remote_env])
        if rc != 0:
            return rc
        log(".env.production copied", elapsed_sec=elapsed())

    # 9. Deploy: cleanup, load image, run container on production
    log("Step 9/9: Deploying to production", "9", elapsed())
    if args.dry_run:
        print(f"  [dry-run] ssh {SSH_HOST} run pre-deploy-cleanup, docker load, docker run", flush=True)
    else:
        # Run pre-deploy-cleanup (frees disk if low)
        cleanup_script = (SCRIPT_DIR / "pre-deploy-cleanup.sh").read_text()
        proc = subprocess.Popen(
            ["ssh", SSH_HOST, "bash -s"],
            stdin=subprocess.PIPE,
            text=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        proc.stdin.write(cleanup_script)
        proc.stdin.close()
        if proc.wait() != 0:
            log("Pre-deploy cleanup failed")
            return 1
        # Stop/remove existing container, load image, run
        deploy_cmd = (
            f"cd {app_path} && "
            f"sudo docker stop {CONTAINER} 2>/dev/null || true && "
            f"sudo docker rm {CONTAINER} 2>/dev/null || true && "
            f"sudo docker load -i {tar_name} && "
            f'sudo docker run -d --name {CONTAINER} --restart unless-stopped '
            f"--env-file .env.production "
            f"-v $(pwd)/.env.production:/app/.env.production "
            f"{IMAGE}:latest"
        )
        log("Loading image and starting container...")
        rc = subprocess.run(["ssh", SSH_HOST, deploy_cmd]).returncode
        if rc != 0:
            return rc
        log(f"Deployed to {SSH_HOST}", elapsed_sec=elapsed())
        time.sleep(3)
        log("Recent logs:")
        run(["ssh", SSH_HOST, f"sudo docker logs {CONTAINER} --tail 30"])

    return 0


if __name__ == "__main__":
    # Unbuffered: logs appear immediately (critical when run from IDE/background)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
