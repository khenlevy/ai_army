"""Environment file handling and validation."""

import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED_VARS = [
    "DO_DROPLET_HOST",
]

OPTIONAL_VARS = [
    "DO_DROPLET_USER",
    "DO_SSH_KEY_PATH",
    "APP_NAME",
    "MONGODB_URI",
    "MONGODB_USER",
    "MONGODB_PASSWORD",
    "MONGODB_HOST",
    "MONGODB_DB",
]


def load_and_validate_env(env_file: str = ".env.production", cwd: Path | None = None) -> dict[str, str]:
    """Load environment file and validate required variables.

    Args:
        env_file: Path to environment file
        cwd: Working directory (default: current directory)

    Returns:
        Dict of loaded env vars (for convenience)

    Raises:
        FileNotFoundError: If env file does not exist
        ValueError: If required variables are missing
    """
    base = cwd or Path.cwd()
    env_path = base / env_file

    if not env_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_path}")

    load_dotenv(env_path)

    missing = []
    for var in REQUIRED_VARS:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Ensure {env_file} exists and contains these variables."
        )

    return {var: os.getenv(var, "") for var in REQUIRED_VARS + OPTIONAL_VARS if os.getenv(var)}
