#!/usr/bin/env bash
# Check production: container image, tags, logs. Run locally: ./scripts/check-production.sh
set -e

SSH_HOST="${SSH_HOST:-ai-army-droplet}"
CONTAINER="${CONTAINER:-ai-army}"
IMAGE="${IMAGE:-ai-army}"

echo "=== Container (name, image, status) ==="
ssh "$SSH_HOST" "sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}'"

echo ""
echo "=== Images ($IMAGE) ==="
ssh "$SSH_HOST" "sudo docker images $IMAGE --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}'"

echo ""
echo "=== Running container image ==="
ssh "$SSH_HOST" "sudo docker inspect $CONTAINER --format '{{.Config.Image}}' 2>/dev/null || echo 'container not found'"

echo ""
echo "=== Latest tag vs version tags (second release = latest, old latest removed?) ==="
ssh "$SSH_HOST" "sudo docker images $IMAGE --format '{{.Tag}}' | sort"

echo ""
echo "=== Recent logs (last 100 lines) ==="
ssh "$SSH_HOST" "sudo docker logs $CONTAINER --tail 100 2>&1"

echo ""
echo "=== Errors in logs ==="
ssh "$SSH_HOST" "sudo docker logs $CONTAINER 2>&1 | grep -iE 'error|exception|traceback|failed' | tail -30" || true
