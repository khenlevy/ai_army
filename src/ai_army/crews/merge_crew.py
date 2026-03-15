"""Merge Crew: Handles open PRs—merges mergeable PRs and resolves conflicts on conflicted PRs."""

import logging
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.config.llm_config import get_llm_model_crewai
from ai_army.config.settings import get_github_repos
from ai_army.config.settings import GitHubRepoConfig
from ai_army.repo_clone import ensure_repo_cloned
from ai_army.tools import (
    CheckoutBranchTool,
    GetPullRequestDetailsTool,
    GitForcePushTool,
    GitRebaseAbortTool,
    GitRebaseContinueTool,
    GitRebaseTool,
    ListOpenIssuesTool,
    ListPullRequestsTool,
    MergePullRequestTool,
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
    """Get Anthropic Claude LLM. Model from config (LLM_MODEL env or settings)."""
    return LLM(
        model=get_llm_model_crewai(),
        temperature=0.2,
    )


def create_merge_crew(
    crew_context: str = "",
    *,
    repo_config: GitHubRepoConfig | None = None,
    clone_path: Path | None = None,
) -> Crew:
    """Create the Merge Crew for handling open PRs."""
    config = _load_agents_config()
    llm = _get_llm()
    merge_config = config["merge_agent"]

    if repo_config is None and clone_path is None:
        repos = get_github_repos()
        if repos:
            repo_config = repos[0]
            clone_path = ensure_repo_cloned(repo_config)
    repo_path_str = str(clone_path) if clone_path else None

    tools = [
        ListPullRequestsTool(repo_config=repo_config),
        GetPullRequestDetailsTool(repo_config=repo_config),
        MergePullRequestTool(repo_config=repo_config),
        CheckoutBranchTool(repo_path=repo_path_str),
        GitRebaseTool(repo_path=repo_path_str),
        GitRebaseContinueTool(repo_path=repo_path_str, agent_name=merge_config["role"]),
        GitRebaseAbortTool(repo_path=repo_path_str),
        GitForcePushTool(repo_path=repo_path_str),
        ReadFileTool(repo_path=repo_path_str),
        WriteFileTool(repo_path=repo_path_str),
        SearchCodebaseTool(repo_path=repo_path_str, repo_config=repo_config),
        RepoStructureTool(repo_path=repo_path_str),
        ListOpenIssuesTool(repo_config=repo_config),
        UpdateIssueTool(repo_config=repo_config),
    ]

    agent = Agent(
        role=merge_config["role"],
        goal=merge_config["goal"],
        backstory=merge_config["backstory"],
        llm=llm,
        verbose=True,
        max_iter=40,
        tools=tools,
    )

    crew_context_block = ""
    if crew_context.strip():
        crew_context_block = f"\n--- Context from previous crews ---\n{crew_context}\n---\n\n"

    list_triage_task = Task(
        description=(
            crew_context_block
            + "List open pull requests using List Pull Requests (state='open'). "
            "For each PR, use Get Pull Request Details with the PR number to get mergeable status, files changed, and linked issue. "
            "If mergeable is True: use Merge Pull Request to merge it, then use Update GitHub Issue to add 'done' to the linked issue (if any). "
            "If mergeable is False (conflicts): proceed to the conflict resolution task for that PR. "
            "Process each open PR. For conflicted PRs, output the PR number and branch name so the next task can resolve them."
        ),
        expected_output="Summary: merged PRs and list of conflicted PRs (number, branch, base) to resolve.",
        agent=agent,
    )

    conflict_task = Task(
        description=(
            "For each conflicted PR from the previous task:\n"
            "1. Use Checkout Branch to switch to the PR's head branch (fetch first if needed—the workspace may be on main).\n"
            "2. Use Git Rebase with base_ref set to the PR's base branch (usually main) to rebase onto it.\n"
            "3. If conflicts occur:\n"
            "   a. Read each conflicting file (the tool output lists them).\n"
            "   b. Resolve conflict markers (<<<<<<< HEAD, =======, >>>>>>> branch) by keeping the correct combination of both sides.\n"
            "   c. Write the resolved file without any conflict markers.\n"
            "   d. Use Git Rebase Continue after resolving each batch of conflicts.\n"
            "4. After all conflicts are resolved, use Git Force Push with the branch name to update the PR.\n"
            "5. Use Merge Pull Request to merge the PR.\n"
            "6. Use Update GitHub Issue to add 'done' to the linked issue (if any).\n"
            "Use Search Codebase and Repo Structure to understand the codebase when resolving conflicts. "
            "Use the linked issue context from Get Pull Request Details to understand intent."
        ),
        expected_output="Summary: each conflicted PR resolved, force-pushed, merged, and linked issues marked done.",
        agent=agent,
        context=[list_triage_task],
    )

    return Crew(
        agents=[agent],
        tasks=[list_triage_task, conflict_task],
        process=Process.sequential,
        verbose=True,
    )


class MergeCrew:
    """Merge Crew - merges mergeable PRs and resolves conflicts on conflicted PRs."""

    @classmethod
    def kickoff(
        cls,
        inputs: dict | None = None,
        crew_context: str = "",
        repo_config: GitHubRepoConfig | None = None,
        clone_path: Path | None = None,
    ) -> str:
        """Run the Merge Crew."""
        crew = create_merge_crew(
            crew_context=crew_context,
            repo_config=repo_config,
            clone_path=clone_path,
        )
        result = crew.kickoff(inputs=inputs or {})
        logger.info("MergeCrew: kickoff completed")
        return result
