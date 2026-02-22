"""Centralized logging configuration for AI-Army."""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure app-wide logging. Call once at startup."""
    format_str = "%(asctime)s | %(levelname)-7s | %(message)s"
    date_format = "%H:%M:%S"

    logging.basicConfig(
        level=level,
        format=format_str,
        datefmt=date_format,
        stream=sys.stdout,
        force=True,
    )

    # Reduce noise from third-party libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
