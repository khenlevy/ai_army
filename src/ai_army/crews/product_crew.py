"""Product Crew: Product Manager + Product Agent.

Creates and prioritizes GitHub issues with lifecycle labels.
Context is aligned with project README and product_context (Product Overview, Product Goal).
Enforces a cap of 8 open issues.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from crewai import Agent, Crew, LLM, Process, Task

from ai_army.tools import (
    CreateIssueTool,
    ListOpenIssuesTool,
    UpdateIssueTool,
    create_github_tools,
)
from ai_army.tools.github_tools import (
    get_open_issue_count,
    get_repo_from_config,
    get_repo_readme,
)

if TYPE_CHECKING:
    from ai_army.config.settings import GitHubRepoConfig

logger = logging.getLogger(__name__)

OPEN_ISSUE_CAP = 8


def _load_agents_config() -> dict:
    """Load agent config from YAML."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "agents.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _load_product_context() -> dict[str, str]:
    """Load Product Overview and Product Goal from config."""
    path = Path(__file__).resolve().parent.parent / "config" / "product_context.yaml"
    if not path.exists():
        return {"product_overview": "", "product_goal": ""}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return {
        "product_overview": (data.get("product_overview") or "").strip(),
        "product_goal": (data.get("product_goal") or "").strip(),
    }


def _get_llm() -> LLM:
    """Get Anthropic Claude LLM."""
    return LLM(
        model="anthropic/claude-3-5-sonnet-20241022",
        temperature=0.3,
    )


def _build_product_context(
    repo_config: "GitHubRepoConfig | None",
) -> dict[str, Any]:
    """Gather README, product_overview, product_goal, and open issue count."""
    ctx = _load_product_context()
    ctx["readme"] = ""
    ctx["open_issue_count"] = 0
    if repo_config:
        try:
            repo = get_repo_from_config(repo_config)
            ctx["readme"] = get_repo_readme(repo)
            ctx["open_issue_count"] = get_open_issue_count(repo)
        except Exception as e:
            logger.warning("Could not fetch repo context: %s", e)
    return ctx


def create_product_crew(
    repo_config: "GitHubRepoConfig | None" = None,
    product_context: dict[str, Any] | None = None,
) -> Crew:
    """Create the Product Crew with PM and Product Agent.

    product_context should contain: readme, product_overview, product_goal, open_issue_count.
    """
    config = _load_agents_config()
    llm = _get_llm()
    ctx = product_context or _build_product_context(repo_config)

    create_issue, update_issue, list_issues, *_ = create_github_tools(repo_config)

    pm_config = config["product_manager"]
    pa_config = config["product_agent"]

    product_manager = Agent(
        role=pm_config["role"],
        goal=pm_config["goal"],
        backstory=pm_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[create_issue, update_issue, list_issues],
    )

    product_agent = Agent(
        role=pa_config["role"],
        goal=pa_config["goal"],
        backstory=pa_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[update_issue, list_issues],
    )

    readme_block = f"\n\n--- Project README (align your work with this) ---\n{ctx.get('readme', '')}\n---" if ctx.get("readme") else ""
    overview_block = f"\n\n--- Product Overview ---\n{ctx.get('product_overview', '')}\n---" if ctx.get("product_overview") else ""
    goal_block = f"\n\n--- Product Goal ---\n{ctx.get('product_goal', '')}\n---" if ctx.get("product_goal") else ""
    cap = ctx.get("open_issue_count", 0)
    cap_rule = (
        f"\n\nCRITICAL: There must be no more than {OPEN_ISSUE_CAP} open issues in this repo. "
        f"Current open issues: {cap}. Do not create new issues when count is already {OPEN_ISSUE_CAP} or higher; "
        "prioritize closing or moving issues to done first."
    )

    pm_task = Task(
        description=(
            "Your decisions must align with the Project README, Product Overview, and Product Goal below."
            + readme_block
            + overview_block
            + goal_block
            + cap_rule
            + "\n\nAnalyze product goals and the current backlog. List open issues using List Open GitHub Issues. "
            "Create new GitHub issues only when under the open-issue cap; otherwise update or prioritize existing ones. "
            "Apply labels: 'backlog' for new items, 'prioritized' for items ready for the Product Agent. "
            "Ensure the backlog reflects the most important product work and stays within the open-issue limit."
        ),
        expected_output="Summary of issues created/updated with their labels (backlog, prioritized).",
        agent=product_manager,
    )

    product_agent_task = Task(
        description=(
            "Your work must align with the Product Overview and Product Goal below."
            + overview_block
            + goal_block
            + "\n\nFor each issue with the 'prioritized' label, enrich it with acceptance criteria and technical specs. "
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
    def kickoff(
        cls,
        inputs: dict | None = None,
        repo_config: "GitHubRepoConfig | None" = None,
    ) -> str:
        """Run the Product Crew. Logs when open issue count reaches cap."""
        product_context = _build_product_context(repo_config)
        if product_context.get("open_issue_count", 0) >= OPEN_ISSUE_CAP:
            logger.warning(
                "Open issue cap reached: %d open issues (max %d). No new issues should be created until count is below cap.",
                product_context["open_issue_count"],
                OPEN_ISSUE_CAP,
            )
            print(
                f"[Product Crew] Open issue cap reached: {product_context['open_issue_count']} open issues (max {OPEN_ISSUE_CAP}). "
                "No new issues should be created until count is below cap."
            )
        crew = create_product_crew(repo_config=repo_config, product_context=product_context)
        return crew.kickoff(inputs=inputs or {})
