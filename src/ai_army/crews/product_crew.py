"""Product Crew: Product Manager + Product Agent.

Creates and prioritizes GitHub issues with lifecycle labels.
"""

from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.tools import (
    CreateIssueTool,
    ListOpenIssuesTool,
    UpdateIssueTool,
)


def _load_agents_config() -> dict:
    """Load agent config from YAML."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "agents.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_llm() -> LLM:
    """Get Anthropic Claude LLM."""
    return LLM(
        model="anthropic/claude-3-5-sonnet-20241022",
        temperature=0.3,
    )


def create_product_crew() -> Crew:
    """Create the Product Crew with PM and Product Agent."""
    config = _load_agents_config()
    llm = _get_llm()

    pm_config = config["product_manager"]
    pa_config = config["product_agent"]

    product_manager = Agent(
        role=pm_config["role"],
        goal=pm_config["goal"],
        backstory=pm_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[CreateIssueTool(), UpdateIssueTool(), ListOpenIssuesTool()],
    )

    product_agent = Agent(
        role=pa_config["role"],
        goal=pa_config["goal"],
        backstory=pa_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[UpdateIssueTool(), ListOpenIssuesTool()],
    )

    pm_task = Task(
        description=(
            "Analyze product goals and the current backlog. List open issues using List Open GitHub Issues. "
            "Create new GitHub issues for high-priority work or update existing ones. "
            "Apply labels: 'backlog' for new items, 'prioritized' for items ready for the Product Agent. "
            "Ensure the backlog reflects the most important product work."
        ),
        expected_output="Summary of issues created/updated with their labels (backlog, prioritized).",
        agent=product_manager,
    )

    product_agent_task = Task(
        description=(
            "For each issue with the 'prioritized' label, enrich it with acceptance criteria and technical specs. "
            "Use List Open GitHub Issues filtered by 'prioritized'. Use Update GitHub Issue to add comments "
            "with acceptance criteria and set the 'ready-for-breakdown' label. "
            "Ensure each issue is clear enough for the Team Lead to break down into sub-tasks."
        ),
        expected_output="Summary of issues enriched and marked ready-for-breakdown.",
        agent=product_agent,
        context=[pm_task],
    )

    return Crew(
        agents=[product_manager, product_agent],
        tasks=[pm_task, product_agent_task],
        process=Process.sequential,
        verbose=True,
    )


class ProductCrew:
    """Product Crew - runs PM and Product Agent to manage backlog."""

    @classmethod
    def kickoff(cls, inputs: dict | None = None) -> str:
        """Run the Product Crew."""
        crew = create_product_crew()
        return crew.kickoff(inputs=inputs or {})
