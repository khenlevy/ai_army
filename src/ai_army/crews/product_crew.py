"""Product Crew: Product Manager + Product Agent.

Creates and prioritizes GitHub issues with lifecycle labels.
Context is aligned with project README and product_context (Product Overview, Product Goal).
Product Agent inspects the codebase, compares implementation vs vision, and opens alignment issues.
Enforces a cap of 8 open issues.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from crewai import Agent, Crew, LLM, Process, Task

from ai_army.config.llm_config import get_llm_model_crewai
from ai_army.tools import (
    CreateIssueTool,
    CreateStructuredIssueTool,
    EnrichIssueTool,
    ListClosedIssuesTool,
    ListOpenIssuesTool,
    RepoStructureTool,
    SearchCodebaseTool,
    UpdateIssueTool,
    create_github_tools,
)
from ai_army.tools.github_tools import (
    extract_product_sections_from_readme,
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
    """Get Anthropic Claude LLM. Model from config (LLM_MODEL env or settings)."""
    return LLM(
        model=get_llm_model_crewai(),
        temperature=0.3,
    )


def _build_product_context(
    repo_config: "GitHubRepoConfig | None",
) -> dict[str, Any]:
    """Gather README, product_overview, product_goal, and open issue count.

    Product overview and goal are taken from the target repo's README when it has
    ## Product Overview and ## Product Goal sections. Otherwise falls back to
    ai_army/config/product_context.yaml (useful when running without a target repo).
    """
    fallback = _load_product_context()
    ctx: dict[str, Any] = {
        "product_overview": fallback["product_overview"],
        "product_goal": fallback["product_goal"],
        "readme": "",
        "open_issue_count": 0,
    }
    if repo_config:
        try:
            repo = get_repo_from_config(repo_config)
            readme = get_repo_readme(repo)
            ctx["readme"] = readme
            ctx["open_issue_count"] = get_open_issue_count(repo)
            sections = extract_product_sections_from_readme(readme)
            if sections["product_overview"]:
                ctx["product_overview"] = sections["product_overview"]
            if sections["product_goal"]:
                ctx["product_goal"] = sections["product_goal"]
        except Exception as e:
            logger.warning("Could not fetch repo context: %s", e)
    return ctx


def create_product_crew(
    repo_config: "GitHubRepoConfig | None" = None,
    product_context: dict[str, Any] | None = None,
    crew_context: str = "",
    repo_path: str | None = None,
) -> Crew:
    """Create the Product Crew with PM and Product Agent.

    product_context should contain: readme, product_overview, product_goal, open_issue_count.
    When repo_path is set, Product Agent gets Search Codebase and Repo Structure to inspect
    the codebase and open alignment issues when implementation diverges from product vision.
    """
    config = _load_agents_config()
    llm = _get_llm()
    ctx = product_context or _build_product_context(repo_config)
    logger.debug("create_product_crew: building crew (open_issues=%s)", ctx.get("open_issue_count", 0))

    create_issue, update_issue, list_issues, *_ = create_github_tools(repo_config)
    create_structured = CreateStructuredIssueTool(
        repo_config=repo_config,
        product_context=ctx,
    )
    enrich_issue = EnrichIssueTool(
        repo_config=repo_config,
        product_context=ctx,
    )

    pm_config = config["product_manager"]
    pa_config = config["product_agent"]

    product_manager = Agent(
        role=pm_config["role"],
        goal=pm_config["goal"],
        backstory=pm_config["backstory"],
        llm=llm,
        verbose=True,
        tools=[create_structured, update_issue, list_issues],
    )

    pa_tools: list = [enrich_issue, update_issue, list_issues]
    list_closed = ListClosedIssuesTool(repo_config=repo_config)
    pa_tools.append(list_closed)
    if repo_path:
        pa_tools.extend(
            [
                SearchCodebaseTool(repo_path=repo_path, repo_config=repo_config),
                RepoStructureTool(repo_path=repo_path),
                create_issue,
            ]
        )

    product_agent = Agent(
        role=pa_config["role"],
        goal=pa_config["goal"],
        backstory=pa_config["backstory"],
        llm=llm,
        verbose=True,
        tools=pa_tools,
    )

    crew_context_block = (
        f"\n\n--- Context from previous crews ---\n{crew_context}\n---"
        if crew_context.strip()
        else ""
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
            + crew_context_block
            + readme_block
            + overview_block
            + goal_block
            + cap_rule
            + "\n\nList open issues using List Open GitHub Issues. "
            "When under the open-issue cap: create new issues using Create Structured GitHub Issue (new issues get 'backlog' and 'prioritized'). "
            "When AT OR OVER the cap: you cannot create new issues. Instead, promote backlog issues to prioritized: "
            "use List Open GitHub Issues filtered by 'backlog', pick 1–2 issues that align with product goals, "
            "and use Update GitHub Issue to add the 'prioritized' label. This feeds the pipeline so the Product Agent can enrich them."
        ),
        expected_output="Summary of new issues created, or backlog issues promoted to prioritized.",
        agent=product_manager,
    )

    alignment_audit_desc = ""
    if repo_path and (ctx.get("product_overview") or ctx.get("product_goal")):
        alignment_audit_desc = (
            "FIRST: Product Alignment Audit. You have Search Codebase and Repo Structure. "
            "Reverse-engineer the codebase: search for key flows from Product Overview (e.g. onboarding, recommendations, tracking). "
            "Compare what exists vs what the Product Overview and Product Goal expect. "
            "When you find gaps (missing flows, incomplete features), open issues using Create GitHub Issue with labels ['backlog','prioritized','feature']. "
            "Prioritize the most critical gaps. Do NOT create issues if open count is already at or over cap. "
            "Then proceed to enrichment.\n\n"
        )

    ticket_alignment_rule = (
        "TICKET ALIGNMENT: Ensure tickets align with what needs to be done. Use List Closed GitHub Issues and List Open GitHub Issues. "
        "If all issues are closed/done but Product Overview and Product Goal indicate the product is incomplete, that is WRONG—open new issues. "
        "We should always move forward: never have a state where everything appears done but the product vision is not fulfilled.\n\n"
    )

    product_agent_task = Task(
        description=(
            alignment_audit_desc
            + ticket_alignment_rule
            + "Your work must align with the Product Overview and Product Goal below."
            + overview_block
            + goal_block
            + "\n\nFor each issue with the 'prioritized' label that does NOT yet have 'ready-for-breakdown', enrich it. "
            "Use List Open GitHub Issues filtered by 'prioritized'. SKIP issues that already have 'ready-for-breakdown' "
            "(do not re-enrich; that creates duplicate comments). Use Enrich GitHub Issue only for prioritized issues "
            "missing ready-for-breakdown. Ensure each enriched issue is clear enough for the Team Lead to break down."
        ),
        expected_output="Summary of alignment/ticket-validation issues opened (if any), and issues enriched and marked ready-for-breakdown.",
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
    """Product Crew - runs PM and Product Agent to manage backlog and alignment audit."""

    @classmethod
    def kickoff(
        cls,
        inputs: dict | None = None,
        repo_config: "GitHubRepoConfig | None" = None,
        crew_context: str = "",
        repo_path: str | None = None,
    ) -> str:
        """Run the Product Crew. Logs when open issue count reaches cap.

        When repo_path is set, Product Agent inspects the codebase and opens alignment issues.
        """
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
        crew = create_product_crew(
            repo_config=repo_config,
            product_context=product_context,
            crew_context=crew_context,
            repo_path=repo_path,
        )
        return crew.kickoff(inputs=inputs or {})
