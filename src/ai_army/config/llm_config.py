"""Central LLM model configuration.

All crews, chains, and token checks use this. Switch model in one place:
- Edit settings.anthropic_llm_model, or
- Set ANTHROPIC_LLM_MODEL env var (e.g. ANTHROPIC_LLM_MODEL=claude-haiku-4-5)
"""

from ai_army.config.settings import settings


def get_llm_model() -> str:
    """Model ID for Anthropic API and LangChain ChatAnthropic (no prefix)."""
    return settings.anthropic_llm_model


def get_llm_model_crewai() -> str:
    """Model ID for CrewAI LLM (anthropic/ prefix for LiteLLM)."""
    return f"anthropic/{settings.anthropic_llm_model}"
