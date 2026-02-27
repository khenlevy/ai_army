"""Check LLM API availability before running scheduled jobs.

Skips execution when rate limit (429) or quota is reached.
Uses count_tokens (zero cost) when available, falls back to minimal completion.
"""

import logging
from typing import Callable

from ai_army.config.llm_config import get_llm_model

logger = logging.getLogger(__name__)

RATE_LIMIT_STATUS = 429


def has_available_tokens() -> bool:
    """Check if Anthropic API has available capacity (no rate limit).

    Tries count_tokens first (no token cost). Falls back to minimal completion if needed.
    Returns False if we get 429 or auth errors.
    """
    try:
        import anthropic

        client = anthropic.Anthropic()
        model = get_llm_model()
        # Prefer count_tokens - zero cost, verifies API is reachable
        if hasattr(client.messages, "count_tokens"):
            client.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
            )
        else:
            # Fallback: minimal completion
            client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}],
            )
        return True
    except Exception as e:
        err_name = type(e).__name__
        if "429" in str(e) or "rate_limit" in err_name.lower():
            logger.warning("Tokens/rate limit reached - skipping this run")
        else:
            logger.warning("API check failed - skipping run: %s", e)
        return False


def run_if_tokens_available(fn: Callable[[], None]) -> None:
    """Run fn only when API has available tokens. Otherwise skip silently."""
    if has_available_tokens():
        fn()
    else:
        logger.info("Skipping job - tokens/rate limit reached, will retry next schedule")
