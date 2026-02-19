"""Team Lead Crew: Breaks features down into sub-tasks before developers take them."""

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


def create_team_lead_crew() -> Crew:
    """Create the Team Lead Crew."""
    config = _load_agents_config()
    llm = _get_llm()

    tl_config = config["team_lead"]

    team_lead = Agent(
        role=tl_config["role"],
        goal=tl_config["goal"],
        backstory=tl_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[ListOpenIssuesTool(), CreateIssueTool(), UpdateIssueTool()],
    )

    breakdown_task = Task(
        description=(
            "List open issues with the 'ready-for-breakdown' label using List Open GitHub Issues. "
            "For each feature issue, break it down into sub-tasks. Create new GitHub issues for each "
            "sub-task (frontend, backend, fullstack) using Create GitHub Issue. "
            "In each sub-issue body, reference the parent: 'Parent: #<parent_number>'. "
            "Apply the appropriate label to each sub-issue: 'frontend', 'backend', or 'fullstack'. "
            "Use Update GitHub Issue on the parent to add the 'broken-down' label and a comment "
            "listing the created sub-issues. "
            "Ensure sub-tasks are clear and implementable by the development agents."
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
    def kickoff(cls, inputs: dict | None = None) -> str:
        """Run the Team Lead Crew."""
        crew = create_team_lead_crew()
        return crew.kickoff(inputs=inputs or {})
