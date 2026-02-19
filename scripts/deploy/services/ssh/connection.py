"""SSH connection management using Paramiko."""

import logging
import os
from pathlib import Path

from paramiko import SSHClient, AutoAddPolicy

logger = logging.getLogger(__name__)


def create_ssh_connection(
    host: str,
    username: str | None = None,
    key_path: str | None = None,
    port: int = 22,
) -> SSHClient:
    """Create and connect SSH client to droplet.

    Args:
        host: Droplet hostname or IP
        username: SSH user (default: root or from DO_DROPLET_USER)
        key_path: Path to private key (default: ~/.ssh/{host} or DO_SSH_KEY_PATH)
        port: SSH port

    Returns:
        Connected SSHClient

    Raises:
        FileNotFoundError: If key file not found
        Exception: On connection failure
    """
    user = username or os.getenv("DO_DROPLET_USER", "root")
    key = key_path or os.getenv("DO_SSH_KEY_PATH") or str(Path.home() / ".ssh" / host)

    key_path_obj = Path(key).expanduser()
    if not key_path_obj.exists():
        raise FileNotFoundError(f"SSH key not found: {key_path_obj}")

    client = SSHClient()
    client.set_missing_host_key_policy(AutoAddPolicy())

    logger.info("Connecting to %s@%s:%d", user, host, port)
    client.connect(
        hostname=host,
        username=user,
        key_filename=str(key_path_obj),
        port=port,
        timeout=30,
    )

    return client


def exec_command(conn: SSHClient, command: str) -> tuple[int, str, str]:
    """Execute command via SSH and return exit code, stdout, stderr.

    Args:
        conn: SSH client
        command: Shell command to run

    Returns:
        (exit_code, stdout, stderr)
    """
    stdin, stdout, stderr = conn.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return exit_code, out, err
