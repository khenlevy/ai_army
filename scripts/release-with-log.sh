#!/usr/bin/env bash
# Run release and save log. Use: ./scripts/release-with-log.sh [--no-bump]
# Log file: /tmp/release-YYYYMMDD-HHMMSS.log
LOG="/tmp/release-$(date +%Y%m%d-%H%M%S).log"
echo "Logging to $LOG"
poetry run python scripts/release.py "$@" 2>&1 | tee "$LOG"
