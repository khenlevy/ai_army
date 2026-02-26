"""Development Crew: Front-end, Server-side, and Full-stack agents.

Pick up broken-down sub-tasks, implement, and submit PRs.
Clones the target repo (GITHUB_TARGET_REPO / GITHUB_REPO_N) into the workspace and works there.
"""

import logging
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
    ListDirTool,
    ListOpenIssuesTool,
    ReadFileTool,
    RepoStructureTool,
    SearchCodebaseTool,
    UpdateIssueTool,
    WriteFileTool,
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
            RepoStructureTool(repo_path=repo_path),
            ListDirTool(repo_path=repo_path),
            ReadFileTool(repo_path=repo_path),
            SearchCodebaseTool(repo_path=repo_path, repo_config=repo_config),
            WriteFileTool(repo_path=repo_path),
            ListOpenIssuesTool(repo_config=repo_config),
            CreateLocalBranchTool(repo_path=repo_path),
            GitCommitTool(repo_path=repo_path),
            GitPushTool(repo_path=repo_path),
            CreatePullRequestTool(repo_config=repo_config),
            UpdateIssueTool(repo_config=repo_config),
        ],
    )


def create_dev_crew(agent_type: str = "frontend", crew_context: str = "") -> Crew:
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
        if not clone_path:
            logger.warning("Dev Crew: repo clone failed for %s", repo_config.repo)
    else:
        logger.warning("Dev Crew: no GitHub repos configured")
    repo_path_str = str(clone_path) if clone_path else None

    logger.debug("create_dev_crew: agent_type=%s, repo_path=%s", agent_type, repo_path_str or "none")
    agent = _create_dev_agent(
        agent_key,
        label_filter,
        repo_path=repo_path_str,
        repo_config=repo_config,
    )

    crew_context_block = (
        f"\n\n--- Context from previous crews ---\n{crew_context}\n---\n\n"
        if crew_context.strip()
        else "\n\n"
    )

    # ReAct-style: Think task first - plan before acting
    # Label filter ensures no overlap: frontend agent only sees frontend, backend only backend, fullstack only fullstack
    think_task = Task(
        description=(
            crew_context_block
            + f"Use List Open GitHub Issues with labels=['{label_filter}'] to find broken-down sub-issues. "
            "Filter the results: pick ONLY issues that do NOT have 'in-progress' or 'in-review' (those are claimed or done). "
            "Pick one available issue to work on. Analyze it and output your implementation plan: "
            "(1) Search query you will use to find relevant code, (2) Files/directories you expect to explore, "
            "(3) Changes you plan to make, (4) Branch name (e.g. feature/issue-N-description), (5) Commit strategy. "
            "Do NOT create a branch, search, read, or edit files yet. Only list issues and output the plan."
        ),
        expected_output="A structured plan: search query, expected files to explore, planned changes, branch name, and commit strategy.",
        agent=agent,
    )

    impl_task = Task(
        description=(
            "Execute the plan. FIRST: Use Update GitHub Issue to add 'in-progress' to the chosen issue (labels only; do NOT add comments). "
            "Then: Create Local Branch. Use Search Codebase (RAG semantic search) with your planned query or issue number to find relevant code "
            "before exploring. Use Repo Structure, List Directory, Read File, Write File to implement. "
            "Make multiple Git Commits as you go. When done: Git Push, Create Pull Request with 'Closes #N', "
            "and Update GitHub Issue to remove 'in-progress' and add 'in-review' (labels only; do NOT add comments). "
            "Your work is the code and PR—do not add comments to issues. If no available issues exist, report that."
        ),
        expected_output="Summary: issue claimed (in-progress), implementation done, branch pushed, PR opened, issue set to in-review.",
        agent=agent,
        context=[think_task],
    )

    return Crew(
        agents=[agent],
        tasks=[think_task, impl_task],
        process=Process.sequential,
        verbose=True,
    )


class DevCrew:
    """Development Crew - Front-end, Server-side, or Full-stack agents."""

    @classmethod
    def kickoff(
        cls,
        agent_type: str = "frontend",
        inputs: dict | None = None,
        crew_context: str = "",
    ) -> str:
        """Run the Development Crew for the given agent type."""
        crew = create_dev_crew(agent_type=agent_type, crew_context=crew_context)
        result = crew.kickoff(inputs=inputs or {})
        logger.info("DevCrew: kickoff completed")
        return result
