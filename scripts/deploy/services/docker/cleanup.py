"""Docker cleanup - local and remote."""

import logging
import os
from pathlib import Path

from paramiko import SSHClient

from scripts.deploy.services.ssh.connection import exec_command

logger = logging.getLogger(__name__)


def cleanup_local_tar(tar_path: Path) -> None:
    """Remove local tar file."""
    if tar_path.exists():
        tar_path.unlink()
        logger.info("Removed local tar %s", tar_path)


def cleanup_local_docker(image_name: str) -> None:
    """Remove local Docker image and prune."""
    import subprocess

    try:
        subprocess.run(["docker", "rmi", image_name], capture_output=True, timeout=30)
        subprocess.run(["docker", "system", "prune", "-f"], capture_output=True, timeout=60)
    except Exception as e:
        logger.warning("Local Docker cleanup warning: %s", e)


def cleanup_remote_docker(
    conn: SSHClient,
    base_path: str,
    release_path: str,
    image_name: str,
    tar_filename: str,
    keep_releases: int = 3,
) -> None:
    """Clean up remote tar file and old images.

    Args:
        conn: SSH client
        base_path: Remote base path
        release_path: Releases subdirectory
        image_name: Image to remove
        tar_filename: Tar file to remove
        keep_releases: Number of releases to keep
    """
    full_path = f"{base_path}/{release_path}"
    tar_full = f"{full_path}/{tar_filename}"

    exec_command(conn, f"rm -f {tar_full}")
    logger.info("Removed remote tar %s", tar_full)

    exec_command(conn, f"docker rmi {image_name} 2>/dev/null || true")
    exec_command(conn, "docker system prune -f 2>/dev/null || true")
