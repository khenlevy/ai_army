"""LangChain chains for QA Crew structured output."""

import logging

from langchain_anthropic import ChatAnthropic

from ai_army.schemas.qa_schemas import ReviewSpec

logger = logging.getLogger(__name__)

LLM_MODEL = "claude-sonnet-4-6"
LLM_TEMPERATURE = 0.2


def _get_llm() -> ChatAnthropic:
    """Get ChatAnthropic LLM."""
    return ChatAnthropic(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )


def review_pr_chain():
    """Return a runnable that produces ReviewSpec from PR context."""
    logger.debug("review_pr_chain: building chain with model=%s", LLM_MODEL)
    llm = _get_llm()
    return llm.with_structured_output(ReviewSpec)
