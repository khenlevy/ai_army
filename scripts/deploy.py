#!/usr/bin/env python3
"""Deploy to Digital Ocean droplet.

Usage:
    python scripts/deploy.py [OPTIONS]
    poetry run deploy [OPTIONS]

Requires deploy dependencies: poetry install --with deploy
Uses .env.production by default.
"""

import sys

# Add project root to path when run as script
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.deploy.release_to_droplet import cli

if __name__ == "__main__":
    cli()
