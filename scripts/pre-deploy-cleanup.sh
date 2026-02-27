#!/usr/bin/env bash
# Pre-deploy cleanup: ensure sufficient disk before Docker pull.
# Root cause of "no space left": disk 100% full.
# Run on droplet before docker pull. Idempotent.
set -e

MIN_AVAIL_KB=$((5 * 1024 * 1024))  # 5GB (pull needs ~2-3GB)
APP_PATH="${RELEASE_APP_PATH:-/root/ai_army}"

avail_kb() {
  df -k / | tail -1 | awk '{print $4}'
}

# Remove old release tars; keep only current + previous (for rollback). Each tar ~1.5GB.
cd "$APP_PATH" 2>/dev/null || true
if [ -d "$APP_PATH" ]; then
  for f in $(ls -t ai-army-*.tar.gz 2>/dev/null | tail -n +3); do
    rm -f "$f" && echo "Removed old tar: $f"
  done
fi

AVAIL_KB=$(avail_kb)
if [ "$AVAIL_KB" -lt "$MIN_AVAIL_KB" ]; then
  echo "=== Low disk (<5GB). Cleaning Docker to free space ==="
  sudo docker stop ai-army 2>/dev/null || true
  sudo docker rm ai-army 2>/dev/null || true
  sudo docker rmi ai-army:latest 2>/dev/null || true
  # Stop and remove ALL containers (including build containers)
  for c in $(sudo docker ps -aq 2>/dev/null); do sudo docker stop "$c" 2>/dev/null || true; done
  for c in $(sudo docker ps -aq 2>/dev/null); do sudo docker rm "$c" 2>/dev/null || true; done
  # Remove all images
  sudo docker rmi $(sudo docker images -q) 2>/dev/null || true
  sudo docker system prune -af --volumes 2>/dev/null || true
  sudo docker builder prune -af 2>/dev/null || true
  AVAIL_KB=$(avail_kb)
  echo "After cleanup: $((AVAIL_KB / 1024 / 1024))GB available"
  if [ "$AVAIL_KB" -lt "$MIN_AVAIL_KB" ]; then
    echo "ERROR: Insufficient disk after cleanup. Need at least 5GB for Docker pull."
    exit 1
  fi
fi
