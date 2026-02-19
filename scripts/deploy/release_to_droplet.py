"""Release to Digital Ocean droplet - main entry point."""

import logging
import os
import sys
from pathlib import Path

import click

from scripts.deploy.services.docker.build import build_and_save_image
from scripts.deploy.services.docker.cleanup import (
    cleanup_local_docker,
    cleanup_local_tar,
    cleanup_remote_docker,
)
from scripts.deploy.services.docker.deploy import deploy_app
from scripts.deploy.services.docker.ensure import ensure_docker
from scripts.deploy.services.docker.upload import upload_and_load_image
from scripts.deploy.services.security.configure import configure_security
from scripts.deploy.services.ssh.connection import create_ssh_connection
from scripts.deploy.utils.environment import load_and_validate_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def release_to_droplet(
    app_name: str,
    dockerfile_path: str = "Dockerfile",
    env_file: str = ".env.production",
    cwd: Path | None = None,
) -> None:
    """Deploy Docker application to Digital Ocean droplet.

    Args:
        app_name: Application name (used for image/container naming)
        dockerfile_path: Path to Dockerfile
        env_file: Path to environment file
        cwd: Working directory
    """
    base = cwd or Path.cwd()
    if cwd:
        os.chdir(cwd)

    load_and_validate_env(env_file=env_file, cwd=base)

    host = os.getenv("DO_DROPLET_HOST")
    if not host:
        raise ValueError("DO_DROPLET_HOST is required")

    image_name = f"{app_name}:latest"
    release_path = "releases"
    base_path = "/root"

    tar_path = None
    conn = None

    try:
        # 1. Build and save image
        logger.info("Step 1: Building and saving image")
        tar_path = build_and_save_image(
            app_name=app_name,
            dockerfile_path=dockerfile_path,
            build_dir=base,
        )

        # 2. SSH connect
        logger.info("Step 2: Connecting via SSH")
        conn = create_ssh_connection(host)

        # 3. Security configuration
        logger.info("Step 3: Configuring security")
        configure_security(conn)

        # 4. Ensure Docker
        logger.info("Step 4: Ensuring Docker is available")
        ensure_docker(conn)

        # 5. Upload and load image
        logger.info("Step 5: Uploading and loading image")
        upload_and_load_image(
            conn=conn,
            tar_path=tar_path,
            release_path=release_path,
            image_name=image_name,
            base_path=base_path,
        )

        # 6. Deploy container
        logger.info("Step 6: Deploying container")
        deploy_app(
            conn=conn,
            app_name=app_name,
            image_name=image_name,
            base_path=base_path,
            release_path=release_path,
        )

        logger.info("Deployment completed successfully")

    finally:
        # 7. Cleanup
        logger.info("Step 7: Cleanup")
        if tar_path and tar_path.exists():
            cleanup_local_tar(tar_path)
        if conn:
            cleanup_remote_docker(
                conn=conn,
                base_path=base_path,
                release_path=release_path,
                image_name=image_name,
                tar_filename=tar_path.name if tar_path and tar_path.exists() else "",
            )
            conn.close()
        cleanup_local_docker(image_name)


@click.command()
@click.option(
    "--app-name",
    help="Application name (defaults to APP_NAME env or current directory name)",
)
@click.option(
    "--dockerfile",
    default="Dockerfile",
    help="Path to Dockerfile",
)
@click.option(
    "--env-file",
    default=".env.production",
    help="Path to environment file",
)
@click.option(
    "--cwd",
    help="Working directory",
    type=click.Path(exists=True, path_type=Path),
)
def cli(app_name: str | None, dockerfile: str, env_file: str, cwd: Path | None) -> None:
    """Deploy Docker application to Digital Ocean droplet."""
    if cwd:
        os.chdir(cwd)

    base = Path(cwd or os.getcwd())
    name = app_name or os.getenv("APP_NAME") or base.name
    if not name:
        click.echo("Error: --app-name or APP_NAME required", err=True)
        sys.exit(1)

    # Ensure env file exists before we change dir
    env_path = base / env_file
    if not env_path.exists():
        click.echo(f"Error: Environment file not found: {env_path}", err=True)
        sys.exit(1)

    try:
        release_to_droplet(
            app_name=name,
            dockerfile_path=dockerfile,
            env_file=env_file,
            cwd=base,
        )
    except Exception as e:
        logger.exception("Deployment failed")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
