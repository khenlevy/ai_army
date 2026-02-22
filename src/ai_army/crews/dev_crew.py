"""Development Crew: Front-end, Server-side, and Full-stack agents.

Pick up broken-down sub-tasks, implement, and submit PRs.
"""

from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.tools import (
    CreateLocalBranchTool,
    CreatePullRequestTool,
    GitCommitTool,
    GitPushTool,
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


def _create_dev_agent(agent_key: str, label_filter: str) -> Agent:
    """Create a development agent for the given role and label filter."""
    config = _load_agents_config()
    llm = _get_llm()
    agent_config = config[agent_key]

    return Agent(
        role=agent_config["role"],
        goal=agent_config["goal"],
        backstory=agent_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[
            ListOpenIssuesTool(),
            CreateLocalBranchTool(),
            GitCommitTool(),
            GitPushTool(),
            CreatePullRequestTool(),
            UpdateIssueTool(),
        ],
    )


def create_dev_crew(agent_type: str = "frontend") -> Crew:
    """Create the Development Crew for a specific agent type.

    Args:
        agent_type: One of 'frontend', 'backend', 'fullstack'
    """
    agent_map = {
        "frontend": "frontend_agent",
        "backend": "server_agent",
        "fullstack": "fullstack_agent",
    }
    agent_key = agent_map.get(agent_type, "frontend_agent")
    label_filter = agent_type if agent_type in agent_map else "frontend"

    agent = _create_dev_agent(agent_key, label_filter)

    task = Task(
        description=(
            f"List open issues with the '{label_filter}' label that are NOT yet 'in-progress' or 'in-review'. "
            "Pick one issue to work on. Use Update GitHub Issue to set 'in-progress' on the issue. "
            "Use Create Local Branch to create a branch in the repo (e.g. feature/issue-N-description). "
            "Implement the feature (edit files as needed). Use Git Commit to stage and commit your changes, "
            "then Git Push to push the branch to the remote. Use Create Pull Request to open a PR with the same "
            "branch name, including 'Closes #N' in the body. Use Update GitHub Issue to set 'in-review' on the issue. "
            "If no implementable issues exist, report that."
        ),
        expected_output="Summary of work done: branch created, changes committed and pushed, PR opened, issue labels updated.",
        agent=agent,
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


class DevCrew:
    """Development Crew - Front-end, Server-side, or Full-stack agents."""

    @classmethod
    def kickoff(cls, agent_type: str = "frontend", inputs: dict | None = None) -> str:
        """Run the Development Crew for the given agent type."""
        crew = create_dev_crew(agent_type=agent_type)
        return crew.kickoff(inputs=inputs or {})
