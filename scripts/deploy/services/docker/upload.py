"""Upload and load Docker image on remote host."""

import logging
from pathlib import Path

from paramiko import SSHClient

from scripts.deploy.services.disk.management import check_disk_space_and_cleanup
from scripts.deploy.services.ssh.connection import exec_command

logger = logging.getLogger(__name__)


def upload_and_load_image(
    conn: SSHClient,
    tar_path: Path,
    release_path: str,
    image_name: str,
    base_path: str = "/root",
) -> None:
    """Upload tar file via SFTP and load into remote Docker.

    Args:
        conn: SSH client
        tar_path: Local path to tar file
        release_path: Remote releases subdirectory
        image_name: Full image name (e.g. ai-army:latest)
        base_path: Remote base path
    """
    full_release = f"{base_path}/{release_path}"
    remote_tar = f"{full_release}/{tar_path.name}"

    check_disk_space_and_cleanup(conn)

    exec_command(conn, f"mkdir -p {full_release}")

    logger.info("Uploading %s to %s", tar_path, remote_tar)
    sftp = conn.open_sftp()
    try:
        sftp.put(str(tar_path), remote_tar)
    finally:
        sftp.close()

    logger.info("Loading image on remote host")
    code, out, err = exec_command(conn, f"docker load < {remote_tar}")
    if code != 0:
        raise RuntimeError(f"Failed to load image on remote: {err or out}")
