#!/usr/bin/env bash
# Prerequisites for production deploy: Docker, app directory (optionally clone repo).
# Single source of truth for what the droplet needs. Idempotent.
#
# Run on droplet: bash scripts/setup-droplet.sh
# Or from host:   ssh ai-army-droplet 'RELEASE_APP_PATH=~/ai_army bash -s' < scripts/setup-droplet.sh
# Release --deploy runs this automatically before deploying.
set -e

APP_PATH="${RELEASE_APP_PATH:-$HOME/ai_army}"
GIT_REPO_URL="${GIT_REPO_URL:-}"  # e.g. https://github.com/owner/ai_army.git

# --- Swap (avoid OOM during Docker build) ---
if [ "$(sudo swapon --show | wc -l)" -eq 0 ]; then
  echo "=== Creating 2GB swap file ==="
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
  echo "Swap enabled"
else
  echo "Swap already active"
fi

# --- Prerequisites: Docker ---
echo "=== Ensuring Docker (prerequisite) ==="
if command -v docker &>/dev/null; then
  echo "Docker already installed: $(docker --version)"
else
  sudo apt-get update -qq
  sudo apt-get install -y docker.io
  sudo systemctl enable docker
  sudo systemctl start docker
  echo "Docker installed: $(docker --version)"
fi

# --- App directory: ensure repo exists ---
echo "=== Ensuring app directory: $APP_PATH ==="
if [ -n "$GIT_REPO_URL" ] && [ ! -d "$APP_PATH/.git" ]; then
  mkdir -p "$(dirname "$APP_PATH")"
  git clone "$GIT_REPO_URL" "$APP_PATH"
  echo "Cloned repo to $APP_PATH"
elif [ -d "$APP_PATH/.git" ]; then
  echo "Repo already present at $APP_PATH"
else
  echo "No repo at $APP_PATH. Set GIT_REPO_URL and re-run, or clone manually."
  exit 1
fi

echo "=== Prerequisites OK. Ensure $APP_PATH/.env.production exists, then deploy. ==="
