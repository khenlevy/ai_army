"""Pre-run branch context for Dev crew.

Builds a summary of in-progress work (branches, commits, files changed) so the agent
can continue existing work instead of starting from scratch.
"""

import logging
import subprocess
from pathlib import Path

from ai_army.config.settings import GitHubRepoConfig
from ai_army.tools.github_helpers import list_issues_for_dev

logger = logging.getLogger(__name__)

DEFAULT_BASE = "main"


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

    issues = list_issues_for_dev(repo_config, agent_type)
    in_progress = [(num, title) for num, title, is_ip in issues if is_ip]
    if not in_progress:
        return ""

    blocks = []
    for issue_number, title in in_progress:
        branch = _find_matching_branch(clone_path, issue_number)
        if not branch:
            continue

        base = DEFAULT_BASE
        code, _ = _run_git(clone_path, "rev-parse", "--verify", "main")
        if code != 0:
            base = "origin/main"

        code, log_out = _run_git(clone_path, "log", f"{base}..{branch}", "--oneline")
        if code != 0:
            log_out = ""

        code, diff_out = _run_git(clone_path, "diff", f"{base}..{branch}", "--stat")
        if code != 0:
            diff_out = ""

        code, remote_out = _run_git(clone_path, "branch", "-r")
        on_remote = code == 0 and f"origin/{branch}" in remote_out

        commit_lines = [l.strip() for l in log_out.splitlines() if l.strip()]
        commit_summary = ", ".join(c.split(" ", 1)[-1][:50] for c in commit_lines[:5])
        if len(commit_lines) > 5:
            commit_summary += f" (+{len(commit_lines) - 5} more)"

        files = []
        for line in diff_out.splitlines():
            if "|" in line:
                files.append(line.split("|")[0].strip())
        files_summary = ", ".join(files[:5]) if files else "none"
        if len(files) > 5:
            files_summary += f", ... (+{len(files) - 5} more)"

        status = "Pushed to remote" if on_remote else "NOT pushed"
        blocks.append(
            f"Issue #{issue_number} ({title}): branch {branch} exists locally.\n"
            f"  Commits: {len(commit_lines)} - {commit_summary}\n"
            f"  Files changed: {files_summary}\n"
            f"  Status: {status}. Checkout branch, continue implementation, then push and open PR."
        )

    if not blocks:
        return ""

    header = "--- In-progress work (continue from here) ---"
    footer = "---"
    return f"\n{header}\n" + "\n\n".join(blocks) + f"\n{footer}\n"
