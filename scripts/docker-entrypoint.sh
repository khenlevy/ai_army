#!/bin/sh
# Copy .env.production to .env so the app loads production config (ENV_FILE defaults to .env).
if [ -f .env.production ]; then
  cp .env.production .env
fi

# Remove stale locks from previous container run (deploy, OOM, crash).
# Workspace is persisted across restarts; orphaned locks block RAG build and git ops.
WORKSPACE="${REPO_WORKSPACE:-/app/.ai_army_workspace}"
if [ -d "$WORKSPACE" ]; then
  if [ -d "$WORKSPACE/.ai_army_index" ]; then
    find "$WORKSPACE/.ai_army_index" -name ".build.lock" 2>/dev/null | while read -r lock; do
      rm -f "$lock" && echo "Removed stale RAG build lock"
    done
  fi
  for repo in "$WORKSPACE"/*/; do
    [ -d "${repo}.git" ] || continue
    lock="${repo}.git/index.lock"
    [ -f "$lock" ] && rm -f "$lock" && echo "Removed stale git index.lock"
  done
fi

exec "$@"
