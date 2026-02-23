"""LangChain chains for Product Crew structured output."""

import logging

from langchain_anthropic import ChatAnthropic

from ai_army.schemas.product_schemas import EnrichIssueSpec, IssueSpec

logger = logging.getLogger(__name__)

LLM_MODEL = "claude-sonnet-4-6"
LLM_TEMPERATURE = 0.3


def _get_llm() -> ChatAnthropic:
    """Get ChatAnthropic LLM."""
    return ChatAnthropic(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )


def create_issue_chain():
    """Return a runnable that produces IssueSpec from a free-form description."""
    logger.debug("create_issue_chain: building chain with model=%s", LLM_MODEL)
    llm = _get_llm()
    return llm.with_structured_output(IssueSpec)


def enrich_issue_chain():
    """Return a runnable that produces EnrichIssueSpec from issue context."""
    logger.debug("enrich_issue_chain: building chain with model=%s", LLM_MODEL)
    llm = _get_llm()
    return llm.with_structured_output(EnrichIssueSpec)
