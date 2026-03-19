"""GitHub issue tools: Create, Update, List Open. CrewAI tools wrapping PyGithub."""

import logging
from pathlib import PurePosixPath
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ai_army.config.settings import GitHubRepoConfig
from ai_army.repo_clone import ensure_repo_cloned
from ai_army.tools.github_helpers import _get_repo_from_config
from ai_army.tools.repo_file_tools import RepoStructureTool

logger = logging.getLogger(__name__)


def _format_issue_body(spec) -> str:
    """Format IssueSpec into GitHub issue body with acceptance criteria."""
    parts = [spec.body] if spec.body else []
    if spec.acceptance_criteria:
        parts.append("\n## Acceptance Criteria")
        for ac in spec.acceptance_criteria:
            parts.append(f"- {ac}")
    if spec.technical_notes:
        parts.append(f"\n## Technical Notes\n{spec.technical_notes}")
    return "\n".join(parts).strip()


def _normalize_scope_path(path: str) -> str:
    """Normalize a scope path for overlap detection."""
    normalized = str(PurePosixPath(path.strip().strip("/")))
    return "" if normalized == "." else normalized


def _paths_overlap(left: str, right: str) -> bool:
    """Return True when two scope paths overlap."""
    left_norm = _normalize_scope_path(left)
    right_norm = _normalize_scope_path(right)
    if not left_norm or not right_norm:
        return False
    return (
        left_norm == right_norm
        or left_norm.startswith(f"{right_norm}/")
        or right_norm.startswith(f"{left_norm}/")
    )


def _scope_sets_overlap(left: list[str], right: list[str]) -> bool:
    """Return True when any path in two file-scope sets overlaps."""
    return any(_paths_overlap(left_path, right_path) for left_path in left for right_path in right)


def _format_issue_meta(*, file_scope: list[str], depends_on: int | None, priority: int) -> str:
    """Format the hidden ai-army metadata block for child issues."""
    scope_lines = ", ".join(f'"{path}"' for path in file_scope)
    depends_on_value = f'"#{depends_on}"' if depends_on else "null"
    return (
        "<!-- ai-army-meta\n"
        f"file_scope: [{scope_lines}]\n"
        f"depends_on: {depends_on_value}\n"
        f"priority: {priority}\n"
        "-->"
    )


class CreateIssueInput(BaseModel):
    """Input schema for CreateIssueTool."""

    title: str = Field(..., description="Issue title")
    body: str = Field(default="", description="Issue body/description")
    labels: list[str] = Field(default_factory=list, description="Labels to apply (e.g. backlog, feature)")


class CreateIssueTool(BaseTool):
    """Create a GitHub issue with title, body, and labels."""

    name: str = "Create GitHub Issue"
    description: str = (
        "Create a new GitHub issue in the target repository. Use for backlog items, features, or bugs. "
        "Apply lifecycle labels like 'backlog', 'prioritized', 'feature', or 'bug'."
    )
    args_schema: Type[BaseModel] = CreateIssueInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, title: str, body: str = "", labels: list[str] | None = None) -> str:
        labels = labels or []
        try:
            repo = _get_repo_from_config(self._repo_config)
            issue = repo.create_issue(title=title, body=body, labels=labels)
            logger.info("Created issue #%s: %s (labels: %s)", issue.number, title, labels)
            return f"Created issue #{issue.number}: {title} (labels: {labels})"
        except Exception as e:
            logger.exception("CreateIssueTool failed: %s", e)
            raise


class CreateStructuredIssueInput(BaseModel):
    """Input schema for CreateStructuredIssueTool."""

    description: str = Field(
        ...,
        description="Free-form description of the issue to create (feature, bug, or backlog item).",
    )


class CreateStructuredIssueTool(BaseTool):
    """Create a GitHub issue with structured output (title, body, labels, acceptance_criteria, technical_notes)."""

    name: str = "Create Structured GitHub Issue"
    description: str = (
        "Create a new GitHub issue from a free-form description. Use for backlog items, features, or bugs. "
        "The tool produces a structured issue with title, body, labels, acceptance criteria, and technical notes. "
        "Apply lifecycle labels like 'backlog', 'prioritized', 'feature', or 'bug'."
    )
    args_schema: Type[BaseModel] = CreateStructuredIssueInput

    def __init__(
        self,
        repo_config: GitHubRepoConfig | None = None,
        product_context: dict[str, Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._repo_config = repo_config
        self._product_context = product_context or {}

    def _run(self, description: str) -> str:
        from ai_army.chains.product_chains import create_issue_chain
        from ai_army.schemas.product_schemas import IssueSpec

        ctx = self._product_context
        context_block = ""
        if ctx.get("readme"):
            context_block += f"\n\nProject README (excerpt):\n{ctx['readme'][:2000]}..."
        if ctx.get("product_overview"):
            context_block += f"\n\nProduct Overview: {ctx['product_overview']}"
        if ctx.get("product_goal"):
            context_block += f"\n\nProduct Goal: {ctx['product_goal']}"

        prompt = f"""Create a structured GitHub issue from the following description.

{context_block}

Description:
{description}

Produce a complete issue with: title, body, labels (always include 'backlog' and 'prioritized' for product issues; add feature/bug as needed), acceptance_criteria (list of strings), and technical_notes."""
        try:
            chain = create_issue_chain()
            spec: IssueSpec = chain.invoke(prompt)
            # Ensure new product issues get backlog+prioritized at creation
            if "backlog" not in spec.labels:
                spec.labels.append("backlog")
            if "prioritized" not in spec.labels:
                spec.labels.append("prioritized")
            logger.info("CreateStructuredIssueTool: produced IssueSpec with title=%s", spec.title)
        except Exception as e:
            logger.exception("CreateStructuredIssueTool chain failed: %s", e)
            return f"Error producing structured issue: {e}"

        body = _format_issue_body(spec)
        create_tool = CreateIssueTool(repo_config=self._repo_config)
        result = create_tool._run(title=spec.title, body=body, labels=spec.labels)
        logger.info("CreateStructuredIssueTool: successfully created issue from structured spec")
        return result


class EnrichIssueInput(BaseModel):
    """Input schema for EnrichIssueTool."""

    issue_number: int = Field(..., description="Issue number to enrich")


class EnrichIssueTool(BaseTool):
    """Enrich an issue with structured acceptance criteria and technical notes."""

    name: str = "Enrich GitHub Issue"
    description: str = (
        "Enrich a prioritized issue with acceptance criteria and technical specs. "
        "Use for issues with the 'prioritized' label. Adds a structured comment and sets 'ready-for-breakdown'."
    )
    args_schema: Type[BaseModel] = EnrichIssueInput

    def __init__(
        self,
        repo_config: GitHubRepoConfig | None = None,
        product_context: dict[str, Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._repo_config = repo_config
        self._product_context = product_context or {}

    def _run(self, issue_number: int) -> str:
        from ai_army.chains.product_chains import enrich_issue_chain
        from ai_army.schemas.product_schemas import EnrichIssueSpec

        repo = _get_repo_from_config(self._repo_config)
        try:
            issue = repo.get_issue(issue_number)
            label_names = [l.name for l in (issue.labels or [])]
            if "ready-for-breakdown" in label_names:
                logger.info("EnrichIssueTool: issue #%s already has ready-for-breakdown, skipping", issue_number)
                return f"Issue #{issue_number} is already enriched (has 'ready-for-breakdown' label). Skipping."
            issue_title = issue.title
            issue_body = issue.body or ""
        except Exception as e:
            logger.warning("Could not fetch issue #%s: %s", issue_number, e)
            return f"Error fetching issue #{issue_number}: {e}"

        ctx = self._product_context
        context_block = ""
        if ctx.get("product_overview"):
            context_block += f"\nProduct Overview: {ctx['product_overview']}"
        if ctx.get("product_goal"):
            context_block += f"\nProduct Goal: {ctx['product_goal']}"

        prompt = f"""Enrich this GitHub issue with acceptance criteria and technical notes.

{context_block}

Issue #{issue_number}: {issue_title}
Body: {issue_body}

Produce acceptance_criteria (list of clear, testable criteria) and technical_notes (implementation hints)."""
        try:
            chain = enrich_issue_chain()
            spec: EnrichIssueSpec = chain.invoke(prompt)
            logger.info("EnrichIssueTool: produced EnrichIssueSpec for issue #%s", issue_number)
        except Exception as e:
            logger.exception("EnrichIssueTool chain failed: %s", e)
            return f"Error producing enrichment: {e}"

        comment_parts = ["[Product Agent]"]
        if spec.acceptance_criteria:
            comment_parts.append("\n## Acceptance Criteria")
            for ac in spec.acceptance_criteria:
                comment_parts.append(f"- {ac}")
        if spec.technical_notes:
            comment_parts.append(f"\n## Technical Notes\n{spec.technical_notes}")
        comment = "\n".join(comment_parts).strip()

        update_tool = UpdateIssueTool(repo_config=self._repo_config)
        result = update_tool._run(
            issue_number=issue_number,
            comment=comment,
            labels_to_add=["ready-for-breakdown"],
        )
        logger.info("EnrichIssueTool: successfully enriched issue #%s with ready-for-breakdown", issue_number)
        return result


class BreakdownAndCreateSubIssuesInput(BaseModel):
    """Input schema for BreakdownAndCreateSubIssuesTool."""

    parent_issue_number: int = Field(
        ...,
        description="Parent issue number (with ready-for-breakdown label) to break down",
    )


class BreakdownAndCreateSubIssuesTool(BaseTool):
    """Break down a feature issue into sub-tasks and create them as GitHub issues."""

    name: str = "Break Down and Create Sub-Issues"
    description: str = (
        "Break down a feature issue with 'ready-for-breakdown' into sub-tasks. "
        "Creates new GitHub issues for each sub-task with frontend/backend/fullstack labels. "
        "Links each sub-issue to the parent and marks the parent as broken-down."
    )
    args_schema: Type[BaseModel] = BreakdownAndCreateSubIssuesInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, parent_issue_number: int) -> str:
        from ai_army.chains.team_lead_chains import breakdown_chain
        from ai_army.schemas.team_lead_schemas import BreakdownSpec

        repo = _get_repo_from_config(self._repo_config)
        try:
            parent = repo.get_issue(parent_issue_number)
            label_names = [l.name for l in (parent.labels or [])]
            if "broken-down" in label_names:
                logger.info("BreakdownAndCreateSubIssuesTool: issue #%s already has broken-down, skipping", parent_issue_number)
                return f"Issue #{parent_issue_number} is already broken down (has 'broken-down' label). Skipping."
            issue_title = parent.title
            issue_body = parent.body or ""
        except Exception as e:
            logger.warning("Could not fetch issue #%s: %s", parent_issue_number, e)
            return f"Error fetching issue #{parent_issue_number}: {e}"

        clone_path = ensure_repo_cloned(self._repo_config) if self._repo_config else None
        repo_structure = ""
        if clone_path:
            repo_structure = RepoStructureTool(repo_path=str(clone_path))._run(max_depth=2)

        prompt = f"""Break down this feature issue into implementable sub-tasks.

Issue #{parent_issue_number}: {issue_title}
Body: {issue_body}

Codebase layout:
{repo_structure or "(repo structure unavailable)"}

Rules:
- Each sub-task MUST include title, body, label, file_scope, depends_on, and priority.
- file_scope must list the directories or files this sub-task is expected to change.
- Sub-tasks MUST NOT have overlapping file_scope entries. If two tasks need the same file, merge them or assign them to the same label.
- Prefer splitting along natural boundaries: frontend UI components vs backend API routes vs shared schemas/integration.
- depends_on must be the 0-based index of a prerequisite sub-task, or null if independent.
- Order sub-tasks so foundations (data models, API endpoints) come before consumers (UI screens, integrations).

Produce sub_tasks with title, body, label (frontend, backend, or fullstack), file_scope, depends_on, and priority for each sub-task.
Set parent_issue to {parent_issue_number}."""
        try:
            chain = breakdown_chain()
            spec: BreakdownSpec = chain.invoke(prompt)
            logger.info(
                "BreakdownAndCreateSubIssuesTool: produced %d sub-tasks for issue #%s",
                len(spec.sub_tasks),
                parent_issue_number,
            )
        except Exception as e:
            logger.exception("BreakdownAndCreateSubIssuesTool chain failed: %s", e)
            return f"Error producing breakdown: {e}"

        if not spec.sub_tasks:
            logger.warning("BreakdownAndCreateSubIssuesTool: no sub-tasks produced for issue #%s", parent_issue_number)
            return f"No sub-tasks produced for issue #{parent_issue_number}"

        for index, sub_task in enumerate(spec.sub_tasks):
            if sub_task.depends_on is not None and not (0 <= sub_task.depends_on < index):
                logger.warning(
                    "BreakdownAndCreateSubIssuesTool: invalid dependency %s for sub-task %d",
                    sub_task.depends_on,
                    index,
                )
                return (
                    "Error producing breakdown: sub-task dependencies must point to an earlier "
                    "sub-task so execution order is well-defined."
                )

        for index, sub_task in enumerate(spec.sub_tasks):
            for prior_index in range(index):
                prior = spec.sub_tasks[prior_index]
                if prior.label == sub_task.label:
                    continue
                if _scope_sets_overlap(prior.file_scope, sub_task.file_scope):
                    logger.warning(
                        "BreakdownAndCreateSubIssuesTool: overlapping scope between task %d (%s) and %d (%s); aligning labels",
                        prior_index,
                        prior.label,
                        index,
                        sub_task.label,
                    )
                    sub_task.label = prior.label

        update_tool = UpdateIssueTool(repo_config=self._repo_config)
        created: list[str] = []
        sub_issue_nums: list[int] = []

        for index, st in enumerate(spec.sub_tasks):
            depends_on_issue: int | None = None
            if st.depends_on is not None and 0 <= st.depends_on < len(sub_issue_nums):
                depends_on_issue = sub_issue_nums[st.depends_on]
            metadata_block = _format_issue_meta(
                file_scope=st.file_scope,
                depends_on=depends_on_issue,
                priority=st.priority,
            )
            body_parts = [f"Parent: #{parent_issue_number}", st.body.strip(), metadata_block]
            body = "\n\n".join(part for part in body_parts if part)
            issue = repo.create_issue(title=st.title, body=body, labels=[st.label])
            created.append(f"Created issue #{issue.number}: {st.title} (labels: ['{st.label}'])")
            sub_issue_nums.append(issue.number)

        if len(sub_issue_nums) == len(spec.sub_tasks):
            sub_list = "\n".join(
                f"- #{n} {st.title} ({st.label}) | scope={st.file_scope} | depends_on={st.depends_on} | priority={st.priority}"
                for n, st in zip(sub_issue_nums, spec.sub_tasks, strict=True)
            )
        else:
            sub_list = "\n".join(
                f"- {st.title} ({st.label}) | scope={st.file_scope} | depends_on={st.depends_on} | priority={st.priority}"
                for st in spec.sub_tasks
            )
        comment = f"[Team Lead]\n\nBroken down into sub-tasks:\n{sub_list}"
        update_tool._run(
            issue_number=parent_issue_number,
            comment=comment,
            labels_to_add=["broken-down"],
        )
        logger.info(
            "BreakdownAndCreateSubIssuesTool: created %d sub-issues for #%s, marked parent broken-down",
            len(spec.sub_tasks),
            parent_issue_number,
        )
        return f"Created {len(spec.sub_tasks)} sub-issues for #{parent_issue_number}:\n" + "\n".join(created)


class UpdateIssueInput(BaseModel):
    """Input schema for UpdateIssueTool."""

    issue_number: int = Field(..., description="Issue number to update")
    comment: str = Field(default="", description="Add a comment to the issue")
    labels_to_add: list[str] = Field(default_factory=list, description="Labels to add")
    labels_to_remove: list[str] = Field(default_factory=list, description="Labels to remove")
    assignee: str = Field(default="", description="Username to assign (empty to skip)")


class UpdateIssueTool(BaseTool):
    """Add comments, update labels, or assign an issue."""

    name: str = "Update GitHub Issue"
    description: str = (
        "Update an existing GitHub issue: add comments, add/remove labels (e.g. in-progress, in-review, done), "
        "or assign to a user. Use lifecycle labels to track progress."
    )
    args_schema: Type[BaseModel] = UpdateIssueInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(
        self,
        issue_number: int,
        comment: str = "",
        labels_to_add: list[str] | None = None,
        labels_to_remove: list[str] | None = None,
        assignee: str = "",
    ) -> str:
        labels_to_add = labels_to_add or []
        labels_to_remove = labels_to_remove or []
        try:
            repo = _get_repo_from_config(self._repo_config)
            issue = repo.get_issue(issue_number)
        except Exception as e:
            logger.exception("UpdateIssueTool: could not fetch issue #%s: %s", issue_number, e)
            raise
        actions = []
        if comment:
            issue.create_comment(comment)
            actions.append("added comment")
        for label in labels_to_add:
            issue.add_to_labels(label)
            actions.append(f"added label '{label}'")
        for label in labels_to_remove:
            issue.remove_from_labels(label)
            actions.append(f"removed label '{label}'")
        if assignee:
            issue.add_to_assignees(assignee)
            actions.append(f"assigned to {assignee}")
        if actions:
            logger.info("UpdateIssueTool: updated issue #%s - %s", issue_number, ", ".join(actions))
        return (
            f"Updated issue #{issue_number}: {', '.join(actions) or 'no changes'}"
            if actions
            else "No updates applied"
        )


class ListOpenIssuesInput(BaseModel):
    """Input schema for ListOpenIssuesTool."""

    labels: list[str] = Field(
        default_factory=list,
        description="Filter by labels (e.g. ready-for-breakdown, frontend). Empty = all open issues.",
    )
    limit: int = Field(default=50, ge=1, le=100, description="Max number of issues to return")


class ListOpenIssuesTool(BaseTool):
    """Fetch open issues for backlog/priorities, optionally filtered by labels."""

    name: str = "List Open GitHub Issues"
    description: str = (
        "List open GitHub issues in the target repository. Filter by labels (e.g. backlog, prioritized, "
        "ready-for-breakdown, frontend, backend, fullstack) to find issues for each workflow stage."
    )
    args_schema: Type[BaseModel] = ListOpenIssuesInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, labels: list[str] | None = None, limit: int = 50) -> str:
        try:
            labels = labels or []
            repo = _get_repo_from_config(self._repo_config)
            raw = repo.get_issues(state="open", labels=labels) if labels else repo.get_issues(state="open")
            issues = list(raw)[:limit]
            result = []
            for i in issues:
                if i.pull_request:
                    continue
                label_names = [l.name for l in (i.labels or [])]
                result.append(f"#{i.number}: {i.title} | labels: {label_names}")
            count = len(result)
            logger.info("ListOpenIssuesTool: found %d open issues (labels=%s)", count, labels or "all")
            return "\n".join(result) if result else "No matching open issues found"
        except Exception as e:
            logger.exception("ListOpenIssuesTool failed: %s", e)
            return f"Error listing issues: {e}"


class ListClosedIssuesInput(BaseModel):
    """Input schema for ListClosedIssuesTool."""

    labels: list[str] = Field(
        default_factory=list,
        description="Filter by labels (e.g. done). Empty = all closed issues.",
    )
    limit: int = Field(default=30, ge=1, le=100, description="Max number of issues to return")


class ListClosedIssuesTool(BaseTool):
    """Fetch closed issues to validate ticket alignment with product vision."""

    name: str = "List Closed GitHub Issues"
    description: str = (
        "List closed GitHub issues. Use to validate that 'done' tickets align with product vision. "
        "If all issues are closed but Product Overview/Goal indicate gaps, that is wrong—open new issues."
    )
    args_schema: Type[BaseModel] = ListClosedIssuesInput

    def __init__(self, repo_config: GitHubRepoConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self._repo_config = repo_config

    def _run(self, labels: list[str] | None = None, limit: int = 30) -> str:
        try:
            labels = labels or []
            repo = _get_repo_from_config(self._repo_config)
            raw = repo.get_issues(state="closed", labels=labels) if labels else repo.get_issues(state="closed")
            issues = list(raw)[:limit]
            result = []
            for i in issues:
                if i.pull_request:
                    continue
                label_names = [l.name for l in (i.labels or [])]
                result.append(f"#{i.number}: {i.title} | labels: {label_names}")
            count = len(result)
            logger.info("ListClosedIssuesTool: found %d closed issues (labels=%s)", count, labels or "all")
            return "\n".join(result) if result else "No matching closed issues found"
        except Exception as e:
            logger.exception("ListClosedIssuesTool failed: %s", e)
            return f"Error listing closed issues: {e}"
