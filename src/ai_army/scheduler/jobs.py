"""Scheduled jobs - Product, Team Lead, Dev crews with token check and context store.

Team Lead and Dev use GitHub-only pre-checks before invoking Claude.
QA is disabled (automation infra to be added later).
"""

import logging

from ai_army.config import get_github_repos
from ai_army.crews.dev_crew import DevCrew
from ai_army.crews.merge_crew import MergeCrew
from ai_army.crews.product_crew import ProductCrew
from ai_army.crews.team_lead_crew import TeamLeadCrew
from ai_army.dev_context import build_workspace_context, list_in_progress_branch_infos
from ai_army.memory.context_store import get_context_store
from ai_army.rag.prebuild import refresh_indexes
from ai_army.rag.runtime_state import agent_window_open, load_runtime_state, repo_key_for_config
from ai_army.repo_clone import ensure_repo_cloned
from ai_army.scheduler.token_check import run_if_tokens_available
from ai_army.tools.github_helpers import (
    count_issues_for_dev,
    count_issues_ready_for_breakdown,
    find_conflicting_agent_prs,
    get_repo_from_config,
    list_issues_for_dev,
)
from ai_army.workspace_manager import cleanup_workspace, fetch_origin, force_push_branch, prepare_workspace, workspace_lock

logger = logging.getLogger(__name__)

_scheduler = None


def set_scheduler(scheduler) -> None:
    """Store scheduler ref for logging next run."""
    global _scheduler
    _scheduler = scheduler


def _log_next_run(job_id: str) -> None:
    if _scheduler:
        job = _scheduler.get_job(job_id)
        if job and job.next_run_time:
            logger.info("Next %s: %s", job_id, job.next_run_time.strftime("%Y-%m-%d %H:%M"))


def _repo_ready(
    repo_config,
    *,
    require_search: bool = False,
    require_issue_ops: bool = False,
    require_code_ops: bool = False,
    require_pr_ops: bool = False,
    require_review_ops: bool = False,
) -> bool:
    """Gate agent jobs on synchronized RAG/runtime readiness."""
    state = load_runtime_state(repo_key_for_config(repo_config))
    missing: list[str] = []
    if not state.repo_path:
        logger.info("Skipping job for %s - runtime state missing (refresh has not completed)", repo_config.repo)
        return False
    if not agent_window_open(state):
        logger.info(
            "Skipping job for %s - agent window not open yet (opens at %s)",
            repo_config.repo,
            state.next_agent_window_at or "unknown",
        )
        return False
    if require_search and not state.capabilities.search_ready:
        missing.append("search_ready")
    if require_issue_ops and not state.capabilities.issue_ops_ready:
        missing.append("issue_ops_ready")
    if require_code_ops and not state.capabilities.code_ops_ready:
        missing.append("code_ops_ready")
    if require_pr_ops and not state.capabilities.pr_ops_ready:
        missing.append("pr_ops_ready")
    if require_review_ops and not state.capabilities.review_ops_ready:
        missing.append("review_ops_ready")
    if missing:
        logger.info(
            "Skipping job for %s - missing capabilities: %s | mode=%s state=%s",
            repo_config.repo,
            ", ".join(missing),
            state.retrieval_mode,
            state.agent_state,
        )
        return False
    return True


def run_rag_refresh_job() -> None:
    """Refresh published RAG snapshots and validate readiness before agent windows."""
    logger.info("RAG refresh starting")
    refresh_indexes()
    logger.info("RAG refresh completed")
    _log_next_run("rag_refresh")


def run_product_crew_job() -> None:
    """Run Product Crew for each configured repo. Skips when API limit reached."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return

    def _run() -> None:
        try:
            lock = workspace_lock(clone_path)
            lock.__enter__()
        except TimeoutError as exc:
            logger.info("Dev Crew (%s): skipping because shared clone is busy: %s", agent_type, exc)
            _log_next_run(f"dev_crew_{agent_type}")
            return
        store = get_context_store()
        store.load()
        crew_context = store.get_summary(exclude="product")
        logger.info("Product Crew: context from previous crews (%d chars)", len(crew_context))
        logger.info("GitHub repos for this run: %s", ", ".join(r.repo for r in repos))
        for repo_config in repos:
            if not _repo_ready(repo_config, require_search=True, require_issue_ops=True):
                continue
            try:
                logger.info("Product Crew starting | repo: %s", repo_config.repo)
                result = ProductCrew.kickoff(repo_config=repo_config, crew_context=crew_context)
                store.add("product", str(result))
                logger.info("Product Crew done successfully | repo: %s", repo_config.repo)
            except Exception as e:
                logger.exception("Product Crew failed | repo: %s | %s", repo_config.repo, e)
        _log_next_run("product_crew")

    run_if_tokens_available(_run)


def run_team_lead_crew_job() -> None:
    """Run Team Lead Crew: break down ready-for-breakdown issues into sub-issues (frontend/backend/fullstack)."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return
    if not _repo_ready(repos[0], require_search=True, require_issue_ops=True):
        _log_next_run("team_lead_crew")
        return

    count = count_issues_ready_for_breakdown(repos[0])
    if count == 0:
        logger.info("Team Lead Crew: no issues ready-for-breakdown (without broken-down), skipping")
        _log_next_run("team_lead_crew")
        return

    def _run() -> None:
        store = get_context_store()
        store.load()
        crew_context = store.get_summary(exclude="team_lead")
        logger.info("Team Lead Crew: context from previous crews (%d chars)", len(crew_context))
        try:
            logger.info("Team Lead Crew starting (%d issues to break down)", count)
            result = TeamLeadCrew.kickoff(crew_context=crew_context)
            store.add("team_lead", str(result))
            logger.info("Team Lead Crew done successfully")
        except Exception as e:
            logger.exception("Team Lead Crew failed: %s", e)
        _log_next_run("team_lead_crew")

    run_if_tokens_available(_run)


def run_dev_crew_job(agent_type: str) -> None:
    """Run Dev Crew for one agent type (frontend, backend, fullstack)."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return
    repo_config = repos[0]
    if not _repo_ready(repo_config, require_search=True, require_code_ops=True, require_pr_ops=True):
        _log_next_run(f"dev_crew_{agent_type}")
        return

    conflict_prs = find_conflicting_agent_prs(repo_config, agent_type)
    count = count_issues_for_dev(repo_config, agent_type)
    if count == 0 and not conflict_prs:
        logger.info("Dev Crew (%s): no available issues and no conflicted PRs, skipping", agent_type)
        _log_next_run(f"dev_crew_{agent_type}")
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("Dev Crew (%s): repo clone unavailable, skipping", agent_type)
        _log_next_run(f"dev_crew_{agent_type}")
        return

    def _run() -> None:
        try:
            with workspace_lock(clone_path):
                store = get_context_store()
                store.load()
                in_progress_count = sum(
                    1 for _, _, is_in_progress in list_issues_for_dev(repo_config, agent_type)
                    if is_in_progress
                )
                crew_context = (
                    store.get_summary(exclude=None)
                    if in_progress_count > 0 or conflict_prs
                    else store.get_summary(exclude="dev")
                )
                logger.info("Dev Crew (%s): context from previous crews (%d chars)", agent_type, len(crew_context))

                if conflict_prs:
                    logger.info("Dev Crew (%s) resolving %d conflicted PR(s)", agent_type, len(conflict_prs))
                    results: list[str] = []
                    for conflict_pr in conflict_prs:
                        prepare_result = prepare_workspace(
                            clone_path,
                            conflict_pr["branch_name"],
                            base_ref=conflict_pr["base_branch"],
                            sync_with_remote=True,
                        )
                        try:
                            if prepare_result.rebased:
                                force_push_branch(clone_path, conflict_pr["branch_name"])
                                results.append(
                                    f"PR #{conflict_pr['pr_number']} rebased cleanly onto "
                                    f"{conflict_pr['base_branch']} and was force-pushed."
                                )
                                continue
                            result = DevCrew.kickoff(
                                agent_type=agent_type,
                                crew_context=crew_context,
                                repo_config=repo_config,
                                clone_path=clone_path,
                                workspace_context=build_workspace_context([prepare_result]),
                                conflict_pr=conflict_pr,
                            )
                            results.append(str(result))
                        finally:
                            cleanup_workspace(clone_path)
                    store.add("dev", "\n\n".join(results))
                    logger.info("Dev Crew (%s) finished conflict resolution cycle", agent_type)
                    return

                branch_infos = list_in_progress_branch_infos(repo_config, clone_path, agent_type)
                prepare_results = (
                    [prepare_workspace(clone_path, info.branch_name) for info in branch_infos]
                    if branch_infos
                    else [prepare_workspace(clone_path)]
                )
                workspace_context = build_workspace_context(prepare_results)
                cleanup_workspace(clone_path)

                logger.info("Dev Crew (%s) starting (%d issues available)", agent_type, count)
                result = DevCrew.kickoff(
                    agent_type=agent_type,
                    crew_context=crew_context,
                    repo_config=repo_config,
                    clone_path=clone_path,
                    workspace_context=workspace_context,
                )
                store.add("dev", str(result))
                logger.info("Dev Crew (%s) done successfully", agent_type)
        except TimeoutError as exc:
            logger.info("Dev Crew (%s): skipping because shared clone is busy: %s", agent_type, exc)
        except Exception as e:
            logger.exception("Dev Crew (%s) failed: %s", agent_type, e)
        finally:
            try:
                cleanup_workspace(clone_path)
            except Exception as cleanup_exc:
                logger.warning("Dev Crew (%s) cleanup failed: %s", agent_type, cleanup_exc)
        _log_next_run(f"dev_crew_{agent_type}")

    run_if_tokens_available(_run)


def run_conflict_check_job() -> None:
    """Auto-rebase open conflicted PRs between agent windows."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping conflict check")
        return
    repo_config = repos[0]
    if not _repo_ready(repo_config, require_code_ops=True, require_pr_ops=True):
        _log_next_run("conflict_check")
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("Conflict check: repo clone unavailable")
        _log_next_run("conflict_check")
        return

    repo = get_repo_from_config(repo_config)
    conflicts: list[tuple[str, dict]] = []
    for agent_type in ("frontend", "backend", "fullstack"):
        for conflict in find_conflicting_agent_prs(repo_config, agent_type):
            conflicts.append((agent_type, conflict))

    if not conflicts:
        logger.info("Conflict check: no conflicted PRs found")
        _log_next_run("conflict_check")
        return

    try:
        with workspace_lock(clone_path):
            for agent_type, conflict in conflicts:
                branch_name = conflict["branch_name"]
                pr_number = conflict["pr_number"]
                try:
                    result = prepare_workspace(
                        clone_path,
                        branch_name,
                        base_ref=conflict["base_branch"],
                        sync_with_remote=True,
                    )
                    if result.rebased:
                        force_push_branch(clone_path, branch_name)
                        logger.info(
                            "Conflict check: rebased and force-pushed PR #%s for %s (%s)",
                            pr_number,
                            agent_type,
                            branch_name,
                        )
                    elif result.rebase_conflicts:
                        pr = repo.get_pull(pr_number)
                        files = ", ".join(result.conflicting_files) or "unknown files"
                        marker = "[AI-Army Conflict Check]"
                        existing_comments = [comment.body or "" for comment in pr.get_issue_comments()]
                        message = (
                            f"{marker}\n\nAI-Army could not auto-rebase this branch cleanly.\n\n"
                            f"Conflicting files: {files}\n"
                            "A follow-up dev conflict-resolution run is required."
                        )
                        if message not in existing_comments:
                            pr.create_issue_comment(message)
                        logger.warning(
                            "Conflict check: PR #%s still has manual conflicts for %s: %s",
                            pr_number,
                            branch_name,
                            files,
                        )
                except Exception as exc:
                    logger.exception("Conflict check failed for PR #%s (%s): %s", pr_number, branch_name, exc)
                finally:
                    try:
                        cleanup_workspace(clone_path)
                    except Exception as cleanup_exc:
                        logger.warning("Conflict check cleanup failed for %s: %s", branch_name, cleanup_exc)
    except TimeoutError as exc:
        logger.info("Conflict check: skipping because shared clone is busy: %s", exc)

    _log_next_run("conflict_check")


def run_merge_crew_job() -> None:
    """Merge agent: merge mergeable PRs and resolve conflicts on conflicted PRs."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping merge crew")
        return
    repo_config = repos[0]
    if not _repo_ready(
        repo_config,
        require_code_ops=True,
        require_pr_ops=True,
        require_review_ops=True,
    ):
        _log_next_run("merge_crew")
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("Merge crew: repo clone unavailable")
        _log_next_run("merge_crew")
        return

    repo = get_repo_from_config(repo_config)
    open_prs = list(repo.get_pulls(state="open")[:1])
    if not open_prs:
        logger.info("Merge crew: no open PRs, skipping")
        _log_next_run("merge_crew")
        return

    def _run() -> None:
        try:
            with workspace_lock(clone_path):
                prepare_workspace(clone_path)
                fetch_origin(clone_path)
                store = get_context_store()
                store.load()
                crew_context = store.get_summary(exclude="merge")
                logger.info("Merge crew: context from previous crews (%d chars)", len(crew_context))
                logger.info("Merge crew starting")
                result = MergeCrew.kickoff(
                    repo_config=repo_config,
                    clone_path=clone_path,
                    crew_context=crew_context,
                )
                store.add("merge", str(result))
                logger.info("Merge crew done successfully")
        except TimeoutError as exc:
            logger.info("Merge crew: skipping because shared clone is busy: %s", exc)
        except Exception as e:
            logger.exception("Merge crew failed: %s", e)
        finally:
            try:
                cleanup_workspace(clone_path)
            except Exception as cleanup_exc:
                logger.warning("Merge crew cleanup failed: %s", cleanup_exc)
        _log_next_run("merge_crew")

    run_if_tokens_available(_run)


# QA Crew disabled - automation infra to be added later
# def run_qa_crew_job() -> None: ...
