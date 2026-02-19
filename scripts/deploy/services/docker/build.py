"""Docker image build and save."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def check_docker_available() -> None:
    """Verify Docker daemon is available.

    Raises:
        RuntimeError: If Docker is not available
    """
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError("Docker is not available. Ensure Docker daemon is running.") from e


def build_and_save_image(
    app_name: str,
    dockerfile_path: str = "Dockerfile",
    build_dir: Path | None = None,
) -> Path:
    """Build Docker image and save to tar file.

    Args:
        app_name: Image name (e.g. ai-army)
        dockerfile_path: Path to Dockerfile
        build_dir: Build context directory (default: cwd)

    Returns:
        Path to saved tar file

    Raises:
        subprocess.CalledProcessError: On build/save failure
    """
    base = build_dir or Path.cwd()
    image_name = f"{app_name}:latest"
    tar_path = base / f"{app_name}-release.tar"

    check_docker_available()

    dockerfile = base / dockerfile_path
    if not dockerfile.exists():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")

    logger.info("Building image %s from %s", image_name, base)
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-t",
            image_name,
            "-f",
            str(dockerfile),
            ".",
        ],
        cwd=base,
        check=True,
        capture_output=False,
    )

    logger.info("Saving image to %s", tar_path)
    with open(tar_path, "wb") as f:
        subprocess.run(
            ["docker", "save", image_name],
            stdout=f,
            check=True,
            capture_output=False,
        )

    return tar_path
