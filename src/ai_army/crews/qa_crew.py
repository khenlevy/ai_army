"""QA Crew: Reviews code, runs tests, and merges PRs when passing."""

import logging
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.config.llm_config import get_llm_model_crewai
from ai_army.tools import (
    ListPullRequestsTool,
    ReviewPullRequestTool,
    create_github_tools,
)

logger = logging.getLogger(__name__)


def _load_agents_config() -> dict:
    """Load agent config from YAML."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "agents.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_llm() -> LLM:
    """Get Anthropic Claude LLM. Model from config (LLM_MODEL env or settings)."""
    return LLM(
        model=get_llm_model_crewai(),
        temperature=0.2,
    )


def create_qa_crew(crew_context: str = "") -> Crew:
    """Create the QA Crew."""
    logger.debug("create_qa_crew: building crew")
    config = _load_agents_config()
    llm = _get_llm()
    _, _, _, _, list_prs, *_ = create_github_tools()
    review_tool = ReviewPullRequestTool()

    automation_config = config["automation_engineer"]

    automation_engineer = Agent(
        role=automation_config["role"],
        goal=automation_config["goal"],
        backstory=automation_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[list_prs, review_tool],
    )

    crew_context_block = (
        f"\n\n--- Context from previous crews ---\n{crew_context}\n---\n\n"
        if crew_context.strip()
        else "\n\n"
    )
    qa_task = Task(
        description=(
            crew_context_block
            + "List open pull requests using List Pull Requests. "
            "For each PR, use Review Pull Request with the PR number. "
            "The tool produces a structured review (merge or request_changes). "
            "It merges when approved and sets 'done' on the linked issue, or adds feedback when changes are needed. "
            "Process each open PR."
        ),
        expected_output="Summary of PRs reviewed: merged, or feedback provided.",
        agent=automation_engineer,
    )

    return Crew(
        agents=[automation_engineer],
        tasks=[qa_task],
        process=Process.sequential,
        verbose=True,
    )


class QACrew:
    """QA Crew - reviews PRs and merges when passing."""

    @classmethod
    def kickoff(cls, inputs: dict | None = None, crew_context: str = "") -> str:
        """Run the QA Crew."""
        crew = create_qa_crew(crew_context=crew_context)
        result = crew.kickoff(inputs=inputs or {})
        logger.info("QACrew: kickoff completed")
        return result
