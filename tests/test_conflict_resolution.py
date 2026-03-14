"""Tests for dependency-aware issue selection and conflicted PR detection."""

from __future__ import annotations

from types import SimpleNamespace

from ai_army.dev_context import build_workspace_context
from ai_army.tools.github_issue_tools import BreakdownAndCreateSubIssuesTool, _format_issue_meta
from ai_army.tools.github_helpers import (
    _issue_linked_in_pr_body,
    find_conflicting_agent_prs,
    list_issues_for_dev,
    parse_issue_execution_meta,
)
from ai_army.workspace_manager import WorkspacePrepareResult


def _label(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _issue(
    number: int,
    title: str,
    labels: list[str],
    body: str = "",
    *,
    state: str = "open",
) -> SimpleNamespace:
    return SimpleNamespace(
        number=number,
        title=title,
        labels=[_label(label) for label in labels],
        body=body,
        pull_request=None,
        state=state,
    )


def _pr(number: int, body: str, head: str, *, mergeable: bool | None) -> SimpleNamespace:
    return SimpleNamespace(
        number=number,
        body=body,
        head=SimpleNamespace(ref=head),
        base=SimpleNamespace(ref="main"),
        mergeable=mergeable,
    )


class _FakeRepo:
    def __init__(self, issues, pulls):
        self._issues = {issue.number: issue for issue in issues}
        self._pulls = {pr.number: pr for pr in pulls}

    def get_issues(self, state: str = "open", labels: list[str] | None = None):
        wanted = set(labels or [])
        issues = list(self._issues.values())
        if wanted:
            issues = [
                issue for issue in issues
                if wanted.issubset({label.name for label in issue.labels})
            ]
        return issues

    def get_pulls(self, state: str = "open"):
        return list(self._pulls.values())

    def get_pull(self, number: int):
        return self._pulls[number]

    def get_issue(self, number: int):
        return self._issues[number]


def test_parse_issue_execution_meta_extracts_scope_dependencies_and_priority() -> None:
    """Structured metadata blocks should round-trip into execution metadata."""
    body = f"""
Parent: #50

{_format_issue_meta(
    file_scope=["apps/mobile/components/", "apps/mobile/hooks/"],
    depends_on=62,
    priority=2,
)}
"""

    meta = parse_issue_execution_meta(body)

    assert meta.file_scope == ["apps/mobile/components/", "apps/mobile/hooks/"]
    assert meta.depends_on == 62
    assert meta.priority == 2


def test_issue_link_detection_supports_repo_qualified_and_resolves() -> None:
    """PR issue detection should accept standard closing keywords and repo-qualified refs."""
    assert _issue_linked_in_pr_body("## Summary\n\nResolves khenlevy/ai_army#57", 57) is True


def test_breakdown_rejects_out_of_order_dependencies(monkeypatch) -> None:
    """Invalid depends_on values should fail instead of being silently dropped."""
    parent_issue = _issue(50, "Parent", ["ready-for-breakdown"])
    repo = _FakeRepo([parent_issue], [])
    tool = BreakdownAndCreateSubIssuesTool()

    fake_chain = lambda: SimpleNamespace(  # noqa: E731
        invoke=lambda _prompt: SimpleNamespace(
            sub_tasks=[
                SimpleNamespace(
                    title="UI task",
                    body="build ui",
                    label="frontend",
                    file_scope=["apps/mobile/components/"],
                    depends_on=1,
                    priority=1,
                ),
                SimpleNamespace(
                    title="API task",
                    body="build api",
                    label="backend",
                    file_scope=["apps/api/"],
                    depends_on=None,
                    priority=2,
                ),
            ]
        )
    )

    monkeypatch.setattr("ai_army.tools.github_issue_tools._get_repo_from_config", lambda _cfg=None: repo)
    monkeypatch.setattr("ai_army.chains.team_lead_chains.breakdown_chain", fake_chain)

    result = tool._run(parent_issue_number=50)

    assert "dependencies must point to an earlier sub-task" in result


def test_list_issues_for_dev_sorts_by_priority_and_skips_blocked_dependencies(monkeypatch) -> None:
    """Dev issue selection should respect priority while skipping unmet dependencies."""
    ready = _issue(
        10,
        "Ready work",
        ["frontend"],
        """<!-- ai-army-meta
file_scope: ["apps/mobile/screens/"]
priority: 2
-->""",
    )
    blocked = _issue(
        11,
        "Blocked work",
        ["frontend"],
        """<!-- ai-army-meta
file_scope: ["apps/mobile/hooks/"]
depends_on: "#99"
priority: 1
-->""",
    )
    dependency = _issue(99, "Dependency", ["backend"], state="open")
    repo = _FakeRepo([ready, blocked, dependency], [])

    monkeypatch.setattr("ai_army.tools.github_helpers._get_repo_from_config", lambda _cfg=None: repo)

    issues = list_issues_for_dev(agent_type="frontend")

    assert issues == [(10, "Ready work", False)]


def test_find_conflicting_agent_prs_returns_open_conflicted_prs(monkeypatch) -> None:
    """Conflicted open PRs should be surfaced for the matching agent type."""
    issue = _issue(
        57,
        "Build Drink Log Entry Form",
        ["frontend", "in-progress", "awaiting-review", "awaiting-merge"],
    )
    pr = _pr(
        64,
        "## Summary\n\nCloses #57",
        "feature/issue-57-drink-log-entry-form",
        mergeable=False,
    )
    repo = _FakeRepo([issue], [pr])

    monkeypatch.setattr("ai_army.tools.github_helpers._get_repo_from_config", lambda _cfg=None: repo)

    conflicts = find_conflicting_agent_prs(agent_type="frontend")

    assert conflicts == [
        {
            "pr_number": 64,
            "branch_name": "feature/issue-57-drink-log-entry-form",
            "base_branch": "main",
            "issue_number": 57,
            "issue_title": "Build Drink Log Entry Form",
        }
    ]


def test_build_workspace_context_includes_conflict_warning() -> None:
    """Workspace prep warnings should be surfaced in agent context."""
    context = build_workspace_context(
        [
            WorkspacePrepareResult(
                branch_name="feature/issue-57-drink-log-entry-form",
                rebase_conflicts=True,
                conflicting_files=["apps/mobile/app.js", "apps/mobile/hooks/useDrinkLog.js"],
            )
        ]
    )

    assert "feature/issue-57-drink-log-entry-form" in context
    assert "apps/mobile/app.js" in context
    assert "merge conflicts with latest main" in context
