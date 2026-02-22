#!/bin/sh
# Copy .env.production to .env so the app loads production config (ENV_FILE defaults to .env).
if [ -f .env.production ]; then
  cp .env.production .env
fi
exec "$@"
