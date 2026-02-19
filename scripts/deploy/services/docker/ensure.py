"""Ensure Docker is installed and running on remote host."""

import logging

from paramiko import SSHClient

from scripts.deploy.services.ssh.connection import exec_command

logger = logging.getLogger(__name__)

DOCKER_INSTALL_SCRIPT = """
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
"""


def ensure_docker(conn: SSHClient) -> None:
    """Verify Docker is installed on remote; install if missing."""
    code, out, err = exec_command(conn, "docker --version")
    if code == 0:
        logger.info("Docker found: %s", out.strip())
        return

    logger.info("Docker not found, installing...")
    for line in DOCKER_INSTALL_SCRIPT.strip().split("\n"):
        line = line.strip()
        if line:
            exec_command(conn, line)

    code2, out2, err2 = exec_command(conn, "docker --version")
    if code2 != 0:
        raise RuntimeError(f"Failed to install Docker: {err2 or out2}")
