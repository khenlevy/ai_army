"""Container deployment on remote host."""

import logging
import os
from pathlib import Path

from paramiko import SSHClient

from scripts.deploy.services.ssh.connection import exec_command

logger = logging.getLogger(__name__)


def deploy_app(
    conn: SSHClient,
    app_name: str,
    image_name: str,
    base_path: str = "/root",
    release_path: str = "releases",
    port: int = 8080,
) -> None:
    """Deploy Docker container on remote host.

    Args:
        conn: SSH client
        app_name: Container name
        image_name: Full image name (e.g. ai-army:latest)
        base_path: Remote base path
        release_path: Releases subdirectory
        port: Host port to bind
    """
    container_name = f"{app_name}-app"
    full_release = f"{base_path}/{release_path}"

    # Stop and remove existing container
    logger.info("Stopping existing container %s", container_name)
    exec_command(conn, f"docker rm -f {container_name} 2>/dev/null || true")

    # Create network if not exists
    exec_command(conn, "docker network create buydy-network 2>/dev/null || true")

    # Build env vars for container
    env_vars = []
    for key in ["ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GITHUB_TARGET_REPO", "OPENAI_API_KEY"]:
        val = os.getenv(key)
        if val:
            env_vars.append(f'-e {key}="{val}"')

    env_str = " ".join(env_vars)

    # Run container
    run_cmd = (
        f"docker run -d --name {container_name} "
        f"--network buydy-network "
        f"--restart unless-stopped "
        f"-m 2g "
        f"-p {port}:8080 "
        f"{env_str} "
        f"{image_name}"
    )
    logger.info("Starting container: %s", container_name)
    code, out, err = exec_command(conn, run_cmd)
    if code != 0:
        raise RuntimeError(f"Failed to start container: {err or out}")

    logger.info("Container %s deployed successfully", container_name)
