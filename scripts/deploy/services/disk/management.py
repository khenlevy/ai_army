"""Disk space checking and cleanup."""

import logging
import re

from paramiko import SSHClient

from scripts.deploy.services.ssh.connection import exec_command

logger = logging.getLogger(__name__)

DISK_THRESHOLD_PERCENT = 85


def parse_disk_usage(output: str) -> list[dict]:
    """Parse df -h output into list of dicts with keys: filesystem, size, used, avail, use_pct, mounted."""
    lines = output.strip().split("\n")
    if len(lines) < 2:
        return []

    result = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 6:
            use_pct = parts[4].rstrip("%")
            try:
                pct = int(use_pct)
                result.append(
                    {
                        "filesystem": parts[0],
                        "size": parts[1],
                        "used": parts[2],
                        "avail": parts[3],
                        "use_pct": pct,
                        "mounted": parts[5],
                    }
                )
            except ValueError:
                pass
    return result


def check_disk_space_and_cleanup(conn: SSHClient) -> dict:
    """Check disk space on remote host, run cleanup if over threshold.

    Returns:
        Dict with disk stats
    """
    code, out, err = exec_command(conn, "df -h /")
    if code != 0:
        raise RuntimeError(f"Failed to check disk space: {err or out}")

    usages = parse_disk_usage(out)
    if not usages:
        return {}

    root = usages[0]
    use_pct = root["use_pct"]

    logger.info("Disk usage: %s%% on %s", use_pct, root.get("mounted", "/"))

    if use_pct >= DISK_THRESHOLD_PERCENT:
        logger.warning("Disk usage above %d%%, running cleanup", DISK_THRESHOLD_PERCENT)
        exec_command(conn, "docker system prune -af 2>/dev/null || true")
        exec_command(conn, "apt-get clean 2>/dev/null || true")

    return root
