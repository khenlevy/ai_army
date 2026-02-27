"""LangChain chains for QA Crew structured output."""

import logging

from langchain_anthropic import ChatAnthropic

from ai_army.config.llm_config import get_llm_model
from ai_army.schemas.qa_schemas import ReviewSpec

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.2


def _get_llm() -> ChatAnthropic:
    """Get ChatAnthropic LLM. Model from config (LLM_MODEL env or settings)."""
    return ChatAnthropic(
        model=get_llm_model(),
        temperature=LLM_TEMPERATURE,
    )


def review_pr_chain():
    """Return a runnable that produces ReviewSpec from PR context."""
    logger.debug("review_pr_chain: building chain with model=%s", get_llm_model())
    llm = _get_llm()
    return llm.with_structured_output(ReviewSpec)
