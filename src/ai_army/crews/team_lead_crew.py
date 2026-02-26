"""Team Lead Crew: Breaks features down into sub-tasks before developers take them."""

import logging
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.tools import (
    BreakdownAndCreateSubIssuesTool,
    ListOpenIssuesTool,
    create_github_tools,
)

logger = logging.getLogger(__name__)


def _load_agents_config() -> dict:
    """Load agent config from YAML."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "agents.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_llm() -> LLM:
    """Get Anthropic Claude LLM."""
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        temperature=0.3,
    )


def create_team_lead_crew(crew_context: str = "") -> Crew:
    """Create the Team Lead Crew."""
    logger.debug("create_team_lead_crew: building crew")
    config = _load_agents_config()
    llm = _get_llm()
    _, _, list_issues, *_ = create_github_tools()
    breakdown_tool = BreakdownAndCreateSubIssuesTool()

    tl_config = config["team_lead"]

    team_lead = Agent(
        role=tl_config["role"],
        goal=tl_config["goal"],
        backstory=tl_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[list_issues, breakdown_tool],
    )

    crew_context_block = (
        f"\n\n--- Context from previous crews ---\n{crew_context}\n---\n\n"
        if crew_context.strip()
        else "\n\n"
    )
    breakdown_task = Task(
        description=(
            crew_context_block
            +             "List open issues with the 'ready-for-breakdown' label using List Open GitHub Issues. "
            "SKIP issues that already have the 'broken-down' label (do not re-break-down; that creates duplicates). "
            "For each ready-for-breakdown issue that is NOT yet broken-down, use Break Down and Create Sub-Issues. "
            "The tool will produce structured sub-tasks (frontend, backend, fullstack) and create "
            "GitHub issues with proper labels and parent linking."
        ),
        expected_output="Summary of features broken down and sub-issues created with their labels.",
        agent=team_lead,
    )

    return Crew(
        agents=[team_lead],
        tasks=[breakdown_task],
        process=Process.sequential,
        verbose=True,
    )


class TeamLeadCrew:
    """Team Lead Crew - breaks features into sub-tasks before devs pick them up."""

    @classmethod
    def kickoff(cls, inputs: dict | None = None, crew_context: str = "") -> str:
        """Run the Team Lead Crew."""
        crew = create_team_lead_crew(crew_context=crew_context)
        result = crew.kickoff(inputs=inputs or {})
        logger.info("TeamLeadCrew: kickoff completed")
        return result
