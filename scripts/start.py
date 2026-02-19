#!/usr/bin/env python3
"""Start AI-Army with environment file selection.

Default: uses .env (development).
Use ENV_FILE=.env.production for production.

Usage:
    python scripts/start.py                    # dev (.env)
    ENV_FILE=.env.production python scripts/start.py   # prod
    python scripts/start.py --env .env.production      # prod via flag
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Start AI-Army")
    parser.add_argument(
        "--env",
        default=os.getenv("ENV_FILE", ".env"),
        help="Environment file path (default: .env)",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="ai-army subcommand (default: schedule)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    env_file = args.env
    os.environ["ENV_FILE"] = env_file

    command = args.command if args.command else ["schedule"]
    cmd = ["poetry", "run", "ai-army"] + command
    return subprocess.run(cmd, cwd=project_root).returncode


if __name__ == "__main__":
    sys.exit(main())
