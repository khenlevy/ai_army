"""IP address detection for security configuration."""

import logging
import re

import requests

logger = logging.getLogger(__name__)

IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)


def get_current_ip() -> str:
    """Get current public IP address via ipify.org.

    Returns:
        Current public IPv4 address

    Raises:
        ValueError: If IP could not be fetched or is invalid
    """
    try:
        resp = requests.get("https://api.ipify.org", timeout=10)
        resp.raise_for_status()
        ip = resp.text.strip()
    except requests.RequestException as e:
        raise ValueError(f"Failed to fetch current IP: {e}") from e

    if not IPV4_PATTERN.match(ip):
        raise ValueError(f"Invalid IP address received: {ip}")

    logger.info("Detected current IP: %s", ip)
    return ip
