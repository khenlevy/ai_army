"""QA Crew: Reviews code, runs tests, and merges PRs when passing."""

from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.tools import (
    ListPullRequestsTool,
    MergePullRequestTool,
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
        temperature=0.2,
    )


def create_qa_crew() -> Crew:
    """Create the QA Crew."""
    config = _load_agents_config()
    llm = _get_llm()

    qa_config = config["qa_agent"]

    qa_agent = Agent(
        role=qa_config["role"],
        goal=qa_config["goal"],
        backstory=qa_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[ListPullRequestsTool(), MergePullRequestTool(), UpdateIssueTool()],
    )

    qa_task = Task(
        description=(
            "List open pull requests using List Pull Requests. "
            "For each PR, review the changes (based on PR title and description). "
            "If the PR looks good and would pass review: use Merge Pull Request to merge it. "
            "Use Update GitHub Issue to add the 'done' label to the linked issue (if you can determine it from the PR body). "
            "If the PR needs changes: use Update GitHub Issue to add a comment with feedback (use the issue number from 'Closes #N' in the PR). "
            "Prefer merging when in doubt - the goal is to keep the pipeline moving."
        ),
        expected_output="Summary of PRs reviewed: merged, or feedback provided.",
        agent=qa_agent,
    )

    return Crew(
        agents=[qa_agent],
        tasks=[qa_task],
        process=Process.sequential,
        verbose=True,
    )


class QACrew:
    """QA Crew - reviews PRs and merges when passing."""

    @classmethod
    def kickoff(cls, inputs: dict | None = None) -> str:
        """Run the QA Crew."""
        crew = create_qa_crew()
        return crew.kickoff(inputs=inputs or {})
