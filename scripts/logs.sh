#!/usr/bin/env bash
# Monitor production logs: SSH to droplet and stream the ai-army container logs.
# Usage: ./scripts/logs.sh [docker logs args...]
# Example: ./scripts/logs.sh --tail 200
set -e

SSH_HOST="${SSH_HOST:-ai-army-droplet}"
CONTAINER="${CONTAINER:-ai-army}"

exec ssh "$SSH_HOST" "sudo docker logs -f ${*:-} $CONTAINER"
