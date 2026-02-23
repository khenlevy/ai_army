"""LangChain chains for Team Lead Crew structured output."""

import logging

from langchain_anthropic import ChatAnthropic

from ai_army.schemas.team_lead_schemas import BreakdownSpec

logger = logging.getLogger(__name__)

LLM_MODEL = "claude-sonnet-4-6"
LLM_TEMPERATURE = 0.3


def _get_llm() -> ChatAnthropic:
    """Get ChatAnthropic LLM."""
    return ChatAnthropic(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )


def breakdown_chain():
    """Return a runnable that produces BreakdownSpec from parent issue context."""
    logger.debug("breakdown_chain: building chain with model=%s", LLM_MODEL)
    llm = _get_llm()
    return llm.with_structured_output(BreakdownSpec)
