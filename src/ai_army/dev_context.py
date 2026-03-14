"""Pre-run branch context for Dev crew.

Builds a summary of in-progress work (branches, commits, files changed) so the agent
can continue existing work instead of starting from scratch.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_army.config.settings import GitHubRepoConfig
from ai_army.tools.github_helpers import list_issues_for_dev
from ai_army.workspace_manager import WorkspacePrepareResult

logger = logging.getLogger(__name__)

DEFAULT_BASE = "main"


@dataclass
class BranchInfo:
    """Summary of a branch tied to an in-progress issue."""

    issue_number: int
    title: str
    branch_name: str
    commit_lines: list[str]
    changed_files: list[str]
    on_remote: bool


def _run_git(repo_path: Path, *args: str) -> tuple[int, str]:
    """Run git in repo_path. Returns (returncode, combined stdout+stderr)."""
    r = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = "\n".join(filter(None, [out, err]))
    return r.returncode, combined


def _find_matching_branch(repo_path: Path, issue_number: int) -> str | None:
    """Find a branch matching feature/issue-{N}-* (local or remote)."""
    code, out = _run_git(repo_path, "branch", "-a")
    if code != 0:
        return None
    target = f"issue-{issue_number}"
    for line in out.splitlines():
        s = line.strip().lstrip("*").strip()
        if "remotes/" in s:
            s = s.replace("remotes/", "").split("/", 1)[-1]
        if target in s and ("feature" in s or "fix" in s.lower() or s.startswith(target)):
            return s
    return None


def list_in_progress_branch_infos(
    repo_config: GitHubRepoConfig | None,
    clone_path: Path | None,
    agent_type: str,
) -> list[BranchInfo]:
    """Return branch summaries for in-progress issues of the given agent type."""
    if not repo_config or not clone_path or not (clone_path / ".git").exists():
        return []

    issues = list_issues_for_dev(repo_config, agent_type)
    in_progress = [(num, title) for num, title, is_ip in issues if is_ip]
    if not in_progress:
        return []

    base = DEFAULT_BASE
    code, _ = _run_git(clone_path, "rev-parse", "--verify", "main")
    if code != 0:
        base = "origin/main"

    infos: list[BranchInfo] = []
    for issue_number, title in in_progress:
        branch = _find_matching_branch(clone_path, issue_number)
        if not branch:
            continue

        code, log_out = _run_git(clone_path, "log", f"{base}..{branch}", "--oneline")
        if code != 0:
            log_out = ""

        code, diff_out = _run_git(clone_path, "diff", f"{base}..{branch}", "--stat")
        if code != 0:
            diff_out = ""

        code, remote_out = _run_git(clone_path, "branch", "-r")
        on_remote = code == 0 and f"origin/{branch}" in remote_out
        commit_lines = [line.strip() for line in log_out.splitlines() if line.strip()]
        changed_files = [
            line.split("|")[0].strip()
            for line in diff_out.splitlines()
            if "|" in line
        ]
        infos.append(
            BranchInfo(
                issue_number=issue_number,
                title=title,
                branch_name=branch,
                commit_lines=commit_lines,
                changed_files=changed_files,
                on_remote=on_remote,
            )
        )
    return infos


def build_workspace_context(prepare_results: list[WorkspacePrepareResult] | None) -> str:
    """Summarize workspace preparation results for the agent context."""
    if not prepare_results:
        return ""
    blocks: list[str] = []
    for result in prepare_results:
        if not result.branch_name:
            continue
        if result.rebase_conflicts:
            file_list = ", ".join(result.conflicting_files) or "unknown files"
            blocks.append(
                f"WARNING: Branch {result.branch_name} has merge conflicts with latest main.\n"
                "You must resolve the conflicts before continuing work.\n"
                f"The conflicting files are: {file_list}"
            )
        elif result.rebased:
            blocks.append(f"Workspace prep: branch {result.branch_name} was rebased onto latest main.")
    if not blocks:
        return ""
    return "\n--- Workspace Preparation ---\n" + "\n\n".join(blocks) + "\n---\n"


def build_branch_context(
    repo_config: GitHubRepoConfig | None,
    clone_path: Path | None,
    agent_type: str,
) -> str:
    """Build context string for in-progress branches.

    Returns a formatted block describing branches that exist for in-progress issues,
    including commits and files changed. Empty string if no in-progress branches found.
    """
    if not repo_config or not clone_path or not (clone_path / ".git").exists():
        return ""

    branch_infos = list_in_progress_branch_infos(repo_config, clone_path, agent_type)
    if not branch_infos:
        return ""

    blocks = []
    for info in branch_infos:
        commit_summary = ", ".join(c.split(" ", 1)[-1][:50] for c in info.commit_lines[:5])
        if len(info.commit_lines) > 5:
            commit_summary += f" (+{len(info.commit_lines) - 5} more)"

        files_summary = ", ".join(info.changed_files[:5]) if info.changed_files else "none"
        if len(info.changed_files) > 5:
            files_summary += f", ... (+{len(info.changed_files) - 5} more)"

        status = "Pushed to remote" if info.on_remote else "NOT pushed"
        blocks.append(
            f"Issue #{info.issue_number} ({info.title}): branch {info.branch_name} exists locally.\n"
            f"  Commits: {len(info.commit_lines)} - {commit_summary}\n"
            f"  Files changed: {files_summary}\n"
            f"  Status: {status}. Checkout branch, continue implementation, then push and open PR."
        )

    if not blocks:
        return ""

    header = "--- In-progress work (continue from here) ---"
    footer = "---"
    return f"\n{header}\n" + "\n\n".join(blocks) + f"\n{footer}\n"
