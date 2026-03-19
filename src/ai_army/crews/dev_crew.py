"""Development Crew: Front-end, Server-side, and Full-stack agents.

Pick up broken-down sub-tasks, implement, and submit PRs.
Clones the target repo (GITHUB_TARGET_REPO / GITHUB_REPO_N) into the workspace and works there.
"""

import logging
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from ai_army.config.llm_config import get_llm_model_crewai
from ai_army.config.settings import get_github_repos
from ai_army.config.settings import GitHubRepoConfig
from ai_army.repo_clone import ensure_repo_cloned
from ai_army.dev_context import build_branch_context
from ai_army.tools.github_tools import (
    extract_product_sections_from_readme,
    get_repo_from_config,
    get_repo_readme,
)
from ai_army.tools import (
    CheckoutBranchTool,
    CreateLocalBranchTool,
    CreatePullRequestTool,
    GitBranchStatusTool,
    GitCommitTool,
    GitForcePushTool,
    GitPushTool,
    GitRebaseAbortTool,
    GitRebaseContinueTool,
    GitRebaseTool,
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
    """Get Anthropic Claude LLM. Model from config (LLM_MODEL env or settings)."""
    return LLM(
        model=get_llm_model_crewai(),
        temperature=0.3,
    )


def _create_dev_agent(
    agent_key: str,
    label_filter: str,
    *,
    repo_path: str | None = None,
    repo_config: GitHubRepoConfig | None = None,
    include_conflict_tools: bool = False,
) -> Agent:
    """Create a development agent for the given role and label filter.

    When repo_path and repo_config are set, the agent works in the cloned target repo
    (branch, commit, push there; GitHub tools target the same repo).
    """
    config = _load_agents_config()
    llm = _get_llm()
    agent_config = config[agent_key]

    tools = [
        RepoStructureTool(repo_path=repo_path),
        ListDirTool(repo_path=repo_path),
        ReadFileTool(repo_path=repo_path),
        SearchCodebaseTool(repo_path=repo_path, repo_config=repo_config),
        WriteFileTool(repo_path=repo_path),
        ListOpenIssuesTool(repo_config=repo_config),
        GitBranchStatusTool(repo_path=repo_path),
        CheckoutBranchTool(repo_path=repo_path),
        CreateLocalBranchTool(repo_path=repo_path),
        GitCommitTool(repo_path=repo_path, agent_name=agent_config["role"]),
        GitPushTool(repo_path=repo_path),
        CreatePullRequestTool(repo_config=repo_config),
        UpdateIssueTool(repo_config=repo_config),
    ]
    if include_conflict_tools:
        tools.extend(
            [
                GitRebaseTool(repo_path=repo_path),
                GitRebaseContinueTool(repo_path=repo_path, agent_name=agent_config["role"]),
                GitRebaseAbortTool(repo_path=repo_path),
                GitForcePushTool(repo_path=repo_path),
            ]
        )

    return Agent(
        role=agent_config["role"],
        goal=agent_config["goal"],
        backstory=agent_config["backstory"],
        llm=llm,
        verbose=True,
        max_iter=40,
        tools=tools,
    )


def create_dev_crew(
    agent_type: str = "frontend",
    crew_context: str = "",
    *,
    repo_config: GitHubRepoConfig | None = None,
    clone_path: Path | None = None,
    workspace_context: str = "",
    conflict_pr: dict | None = None,
) -> Crew:
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

    if repo_config is None and clone_path is None:
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
        include_conflict_tools=True,
    )

    product_vision_block = ""
    if repo_config:
        try:
            repo = get_repo_from_config(repo_config)
            readme = get_repo_readme(repo)
            sections = extract_product_sections_from_readme(readme)
            if sections.get("product_overview") or sections.get("product_goal"):
                parts = []
                if sections.get("product_overview"):
                    parts.append(f"Product Overview:\n{sections['product_overview']}")
                if sections.get("product_goal"):
                    parts.append(f"Product Goal:\n{sections['product_goal']}")
                product_vision_block = (
                    "\n--- Product Vision (align your work; you have full context) ---\n"
                    + "\n\n".join(parts)
                    + "\n---\n\n"
                )
        except Exception as e:
            logger.debug("Dev crew: could not fetch product vision: %s", e)

    branch_context = (
        build_branch_context(repo_config, clone_path, agent_type)
        if repo_config and clone_path
        else ""
    )
    crew_context_block = product_vision_block
    if branch_context:
        crew_context_block += branch_context + "\n"
    if workspace_context.strip():
        crew_context_block += workspace_context.strip() + "\n"
    if crew_context.strip():
        crew_context_block += f"\n--- Context from previous crews ---\n{crew_context}\n---\n\n"
    if not crew_context_block.strip():
        crew_context_block = "\n"

    if conflict_pr:
        conflict_task = Task(
            description=(
                crew_context_block
                + "Your open PR "
                + f"#{conflict_pr['pr_number']} on branch {conflict_pr['branch_name']} has merge conflicts with {conflict_pr['base_branch']}. "
                + f"The PR was originally for issue #{conflict_pr['issue_number']}: {conflict_pr['issue_title']}.\n\n"
                "Your job is to resolve the conflicts:\n"
                f"1. Use Checkout Branch to switch to {conflict_pr['branch_name']}\n"
                f"2. Use Git Rebase with base_ref='{conflict_pr['base_branch']}' to attempt a rebase\n"
                "3. If the rebase reports conflicts:\n"
                "   a. Read each conflicting file to understand both sides of the conflict\n"
                f"   b. The conflict markers (<<<<<<< HEAD, =======, >>>>>>> {conflict_pr['branch_name']}) show:\n"
                f"      - HEAD side: changes from {conflict_pr['base_branch']} (other merged PRs)\n"
                f"      - {conflict_pr['branch_name']} side: your original changes\n"
                "   c. Resolve each file by keeping the correct combination of both sides\n"
                "   d. Write the resolved file without any conflict markers\n"
                "   e. Use Git Rebase Continue after resolving the files\n"
                f"4. After all conflicts are resolved, use Git Force Push with branch='{conflict_pr['branch_name']}' to update the existing PR branch\n"
                "5. Verify the branch is clean and ready to merge\n\n"
                "Do NOT create a new PR. Do NOT change the scope of the original work. "
                "Only resolve the merge conflicts so the existing PR can be merged cleanly."
            ),
            expected_output=(
                "Summary: conflicting PR branch rebased or manually resolved, force-pushed, "
                "and ready to merge."
            ),
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[conflict_task],
            process=Process.sequential,
            verbose=True,
        )

    # ReAct-style: Think task first - plan before acting
    # Label filter ensures no overlap: frontend agent only sees frontend, backend only backend, fullstack only fullstack
    think_task = Task(
        description=(
            crew_context_block
            + f"Use List Open GitHub Issues with labels=['{label_filter}'] to find broken-down sub-issues. "
            "Pick issues that are either (a) available (no in-progress/in-review/awaiting-*) OR (b) in-progress with no PR yet (continue existing work). "
            "If In-progress work is listed in context above, prefer continuing that branch; use Git Branch Status to see what's done. "
            "Pick one issue to work on. Analyze it and output your implementation plan: "
            "(1) Search query you will use to find relevant code, (2) Files/directories you expect to explore, "
            "(3) Changes you plan to make, (4) Branch name (e.g. feature/issue-N-description), (5) Commit strategy. "
            "Do NOT create a branch, search, read, or edit files yet. Only list issues and output the plan."
        ),
        expected_output="A structured plan: search query, expected files to explore, planned changes, branch name, and commit strategy.",
        agent=agent,
    )

    impl_task = Task(
        description=(
            "Execute the plan. If continuing an existing branch: use Checkout Branch first (do NOT use Create Local Branch for existing branches). "
            "If workspace preparation reported merge conflicts with main, resolve them before coding by using Git Rebase, Read File, Write File, and Git Rebase Continue. "
            "For new work: FIRST use Update GitHub Issue to add 'in-progress' to the chosen issue (labels only; do NOT add comments), "
            "then Create Local Branch. Use Search Codebase (RAG semantic search) with your planned query or issue number to find relevant code "
            "before exploring. Use Repo Structure, List Directory, Read File, Write File to implement. "
            "Make multiple Git Commits as you go. When done: Git Push, Create Pull Request with 'Closes #N', "
            "and Update GitHub Issue to remove 'in-progress' and add 'in-review', 'awaiting-review', 'awaiting-merge' (labels only; do NOT add comments). "
            "The PR must be created—your work is complete only when the PR exists and the issue has awaiting-review and awaiting-merge. "
            "If no available issues exist, report that."
        ),
        expected_output="Summary: issue claimed (in-progress), implementation done, branch pushed, PR opened, issue set to in-review, awaiting-review, awaiting-merge.",
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
        repo_config: GitHubRepoConfig | None = None,
        clone_path: Path | None = None,
        workspace_context: str = "",
        conflict_pr: dict | None = None,
    ) -> str:
        """Run the Development Crew for the given agent type."""
        crew = create_dev_crew(
            agent_type=agent_type,
            crew_context=crew_context,
            repo_config=repo_config,
            clone_path=clone_path,
            workspace_context=workspace_context,
            conflict_pr=conflict_pr,
        )
        result = crew.kickoff(inputs=inputs or {})
        logger.info("DevCrew: kickoff completed")
        return result
