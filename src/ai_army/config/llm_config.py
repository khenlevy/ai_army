"""Central LLM model configuration.

All crews, chains, and token checks use this. Switch model in one place:
- Edit settings.llm_model, or
- Set LLM_MODEL env var (e.g. LLM_MODEL=claude-3-5-sonnet-20241022)
"""

from ai_army.config.settings import settings


def get_llm_model() -> str:
    """Model ID for Anthropic API and LangChain ChatAnthropic (no prefix)."""
    return settings.llm_model


def get_llm_model_crewai() -> str:
    """Model ID for CrewAI LLM (anthropic/ prefix for LiteLLM)."""
    return f"anthropic/{settings.llm_model}"
