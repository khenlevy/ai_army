"""Development Crew: Front-end, Server-side, and Full-stack agents.

Pick up broken-down sub-tasks, implement, and submit PRs.
Clones the target repo (GITHUB_TARGET_REPO / GITHUB_REPO_N) into the workspace and works there.
"""

from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.config.settings import get_github_repos
from ai_army.config.settings import GitHubRepoConfig
from ai_army.repo_clone import ensure_repo_cloned
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
        model="anthropic/claude-sonnet-4-6",
        temperature=0.3,
    )


def _create_dev_agent(
    agent_key: str,
    label_filter: str,
    *,
    repo_path: str | None = None,
    repo_config: GitHubRepoConfig | None = None,
) -> Agent:
    """Create a development agent for the given role and label filter.

    When repo_path and repo_config are set, the agent works in the cloned target repo
    (branch, commit, push there; GitHub tools target the same repo).
    """
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
            ListOpenIssuesTool(repo_config=repo_config),
            CreateLocalBranchTool(repo_path=repo_path),
            GitCommitTool(repo_path=repo_path),
            GitPushTool(repo_path=repo_path),
            CreatePullRequestTool(repo_config=repo_config),
            UpdateIssueTool(repo_config=repo_config),
        ],
    )


def create_dev_crew(agent_type: str = "frontend") -> Crew:
    """Create the Development Crew for a specific agent type.

    Clones the target repo (from GITHUB_TARGET_REPO or first GITHUB_REPO_N) into
    REPO_WORKSPACE (default .ai_army_workspace) so the agent works in a real clone:
    branch, commit, push, then open PR via API.

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

    repo_config: GitHubRepoConfig | None = None
    clone_path = None
    repos = get_github_repos()
    if repos:
        repo_config = repos[0]
        clone_path = ensure_repo_cloned(repo_config)
    repo_path_str = str(clone_path) if clone_path else None

    agent = _create_dev_agent(
        agent_key,
        label_filter,
        repo_path=repo_path_str,
        repo_config=repo_config,
    )

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
