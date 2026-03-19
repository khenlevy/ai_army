"""Scheduled jobs - Product, Team Lead, Dev crews with token check and context store.

Team Lead and Dev use GitHub-only pre-checks before invoking Claude.
QA is disabled (automation infra to be added later).
"""

import logging
import time

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
from ai_army.scheduler.token_check import invalidate_token_cache, run_if_tokens_available
from ai_army.tools.github_helpers import (
    count_backlog_promotable,
    count_issues_for_dev,
    count_issues_ready_for_breakdown,
    count_prioritized_needing_enrichment,
    find_conflicting_agent_prs,
    get_open_issue_count,
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
            logger.info("[%s] Next run: %s", job_id, job.next_run_time.strftime("%Y-%m-%d %H:%M"))


def _repo_ready(
    repo_config,
    *,
    job_tag: str = "",
    require_search: bool = False,
    require_issue_ops: bool = False,
    require_code_ops: bool = False,
    require_pr_ops: bool = False,
    require_review_ops: bool = False,
) -> bool:
    """Gate agent jobs on synchronized RAG/runtime readiness."""
    state = load_runtime_state(repo_key_for_config(repo_config))
    tag = f"[{job_tag}] " if job_tag else ""
    missing: list[str] = []
    if not state.repo_path:
        logger.info("%sSkipping - runtime state missing (refresh has not completed)", tag)
        return False
    if not agent_window_open(state):
        logger.info(
            "%sSkipping - agent window not open yet (opens at %s)",
            tag,
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
            "%sSkipping - missing capabilities: %s | mode=%s state=%s",
            tag,
            ", ".join(missing),
            state.retrieval_mode,
            state.agent_state,
        )
        return False
    return True


def run_rag_refresh_job() -> None:
    """Refresh published RAG snapshots and validate readiness before agent windows."""
    t0 = time.monotonic()
    logger.info("[rag_refresh] starting")
    invalidate_token_cache()
    refresh_indexes()
    elapsed = time.monotonic() - t0
    logger.info("[rag_refresh] done | elapsed: %.1fs", elapsed)
    _log_next_run("rag_refresh")


OPEN_ISSUE_CAP = 8


def run_product_crew_job() -> None:
    """Run Product Crew for each configured repo. Skips when API limit reached or idle (backlog full, nothing to enrich)."""
    TAG = "product_crew"
    repos = get_github_repos()
    if not repos:
        logger.warning("[%s] No GitHub repos configured, skipping", TAG)
        return

    repo_config = repos[0]
    if not _repo_ready(repo_config, job_tag=TAG, require_search=True, require_issue_ops=True):
        _log_next_run(TAG)
        return

    repo = get_repo_from_config(repo_config)
    open_count = get_open_issue_count(repo)
    prioritized_needing = count_prioritized_needing_enrichment(repo_config)
    backlog_promotable = count_backlog_promotable(repo_config)
    if open_count >= OPEN_ISSUE_CAP and prioritized_needing == 0 and backlog_promotable == 0:
        logger.info(
            "[%s] Skipping - backlog full (%d issues), nothing to enrich, no backlog to promote",
            TAG,
            open_count,
        )
        _log_next_run(TAG)
        return

    def _run() -> None:
        t0 = time.monotonic()
        store = get_context_store()
        store.load()
        crew_context = store.get_summary(exclude="product")
        logger.info("[%s] context from previous crews (%d chars)", TAG, len(crew_context))
        for cfg in repos:
            if not _repo_ready(cfg, job_tag=TAG, require_search=True, require_issue_ops=True):
                continue
            state = load_runtime_state(repo_key_for_config(cfg))
            repo_path = state.repo_path if state else None
            try:
                logger.info("[%s] starting | repo: %s", TAG, cfg.repo)
                result = ProductCrew.kickoff(
                    repo_config=cfg,
                    crew_context=crew_context,
                    repo_path=repo_path,
                )
                store.add("product", str(result))
                elapsed = time.monotonic() - t0
                logger.info("[%s] done | repo: %s | elapsed: %.1fs", TAG, cfg.repo, elapsed)
            except Exception as e:
                logger.exception("[%s] failed | repo: %s | %s", TAG, cfg.repo, e)
        _log_next_run(TAG)

    run_if_tokens_available(_run)


def run_team_lead_crew_job() -> None:
    """Run Team Lead Crew: break down ready-for-breakdown issues into sub-issues (frontend/backend/fullstack)."""
    TAG = "team_lead_crew"
    repos = get_github_repos()
    if not repos:
        logger.warning("[%s] No GitHub repos configured, skipping", TAG)
        return
    if not _repo_ready(repos[0], job_tag=TAG, require_search=True, require_issue_ops=True):
        _log_next_run(TAG)
        return

    count = count_issues_ready_for_breakdown(repos[0])
    if count == 0:
        logger.info("[%s] Skipping - no issues ready-for-breakdown (without broken-down)", TAG)
        _log_next_run(TAG)
        return

    def _run() -> None:
        t0 = time.monotonic()
        store = get_context_store()
        store.load()
        crew_context = store.get_summary(exclude="team_lead")
        logger.info("[%s] context from previous crews (%d chars)", TAG, len(crew_context))
        try:
            logger.info("[%s] starting | %d issues to break down", TAG, count)
            result = TeamLeadCrew.kickoff(crew_context=crew_context)
            store.add("team_lead", str(result))
            elapsed = time.monotonic() - t0
            logger.info("[%s] done | repo: %s | elapsed: %.1fs", TAG, repos[0].repo, elapsed)
        except Exception as e:
            logger.exception("[%s] failed: %s", TAG, e)
        _log_next_run(TAG)

    run_if_tokens_available(_run)


def run_dev_crew_job(agent_type: str) -> None:
    """Run Dev Crew for one agent type (frontend, backend, fullstack)."""
    TAG = f"dev_crew_{agent_type}"
    repos = get_github_repos()
    if not repos:
        logger.warning("[%s] No GitHub repos configured, skipping", TAG)
        return
    repo_config = repos[0]
    if not _repo_ready(repo_config, job_tag=TAG, require_search=True, require_code_ops=True, require_pr_ops=True):
        _log_next_run(TAG)
        return

    conflict_prs = find_conflicting_agent_prs(repo_config, agent_type)
    count = count_issues_for_dev(repo_config, agent_type)
    if count == 0 and not conflict_prs:
        logger.info("[%s] Skipping - no available issues and no conflicted PRs", TAG)
        _log_next_run(TAG)
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("[%s] Repo clone unavailable, skipping", TAG)
        _log_next_run(TAG)
        return

    def _run() -> None:
        t0 = time.monotonic()
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
                logger.info("[%s] context from previous crews (%d chars)", TAG, len(crew_context))

                if conflict_prs:
                    logger.info("[%s] resolving %d conflicted PR(s)", TAG, len(conflict_prs))
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
                    elapsed = time.monotonic() - t0
                    logger.info("[%s] done (conflict resolution) | repo: %s | elapsed: %.1fs", TAG, repo_config.repo, elapsed)
                    return

                branch_infos = list_in_progress_branch_infos(repo_config, clone_path, agent_type)
                prepare_results = (
                    [prepare_workspace(clone_path, info.branch_name) for info in branch_infos]
                    if branch_infos
                    else [prepare_workspace(clone_path)]
                )
                workspace_context = build_workspace_context(prepare_results)
                cleanup_workspace(clone_path)

                logger.info("[%s] starting | %d issues available", TAG, count)
                result = DevCrew.kickoff(
                    agent_type=agent_type,
                    crew_context=crew_context,
                    repo_config=repo_config,
                    clone_path=clone_path,
                    workspace_context=workspace_context,
                )
                store.add("dev", str(result))
                elapsed = time.monotonic() - t0
                logger.info("[%s] done | repo: %s | elapsed: %.1fs", TAG, repo_config.repo, elapsed)
        except TimeoutError as exc:
            logger.info("[%s] Skipping - shared clone is busy: %s", TAG, exc)
        except Exception as e:
            logger.exception("[%s] failed: %s", TAG, e)
        finally:
            try:
                cleanup_workspace(clone_path)
            except Exception as cleanup_exc:
                logger.warning("[%s] cleanup failed: %s", TAG, cleanup_exc)
        _log_next_run(TAG)

    run_if_tokens_available(_run)


def run_conflict_check_job() -> None:
    """Auto-rebase open conflicted PRs between agent windows."""
    TAG = "conflict_check"
    repos = get_github_repos()
    if not repos:
        logger.warning("[%s] No GitHub repos configured, skipping", TAG)
        return
    repo_config = repos[0]
    if not _repo_ready(repo_config, job_tag=TAG, require_code_ops=True, require_pr_ops=True):
        _log_next_run(TAG)
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("[%s] Repo clone unavailable, skipping", TAG)
        _log_next_run(TAG)
        return

    repo = get_repo_from_config(repo_config)
    conflicts: list[tuple[str, dict]] = []
    for agent_type in ("frontend", "backend", "fullstack"):
        for conflict in find_conflicting_agent_prs(repo_config, agent_type):
            conflicts.append((agent_type, conflict))

    if not conflicts:
        logger.info("[%s] No conflicted PRs found", TAG)
        _log_next_run(TAG)
        return

    t0 = time.monotonic()
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
                            "[%s] rebased and force-pushed PR #%s for %s (%s)",
                            TAG,
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
                            "[%s] PR #%s still has manual conflicts for %s: %s",
                            TAG,
                            pr_number,
                            branch_name,
                            files,
                        )
                except Exception as exc:
                    logger.exception("[%s] failed for PR #%s (%s): %s", TAG, pr_number, branch_name, exc)
                finally:
                    try:
                        cleanup_workspace(clone_path)
                    except Exception as cleanup_exc:
                        logger.warning("[%s] cleanup failed for %s: %s", TAG, branch_name, cleanup_exc)
        elapsed = time.monotonic() - t0
        logger.info("[%s] done | repo: %s | elapsed: %.1fs", TAG, repo_config.repo, elapsed)
    except TimeoutError as exc:
        logger.info("[%s] Skipping - shared clone is busy: %s", TAG, exc)

    _log_next_run(TAG)


def run_merge_crew_job() -> None:
    """Merge agent: merge mergeable PRs and resolve conflicts on conflicted PRs."""
    TAG = "merge_crew"
    repos = get_github_repos()
    if not repos:
        logger.warning("[%s] No GitHub repos configured, skipping", TAG)
        return
    repo_config = repos[0]
    if not _repo_ready(
        repo_config,
        job_tag=TAG,
        require_code_ops=True,
        require_pr_ops=True,
        require_review_ops=True,
    ):
        _log_next_run(TAG)
        return

    clone_path = ensure_repo_cloned(repo_config)
    if not clone_path:
        logger.warning("[%s] Repo clone unavailable, skipping", TAG)
        _log_next_run(TAG)
        return

    repo = get_repo_from_config(repo_config)
    open_prs = list(repo.get_pulls(state="open"))
    if not open_prs:
        logger.info("[%s] No open PRs, skipping", TAG)
        _log_next_run(TAG)
        return

    logger.info("[%s] %d open PR(s) to process", TAG, len(open_prs))

    def _run() -> None:
        t0 = time.monotonic()
        try:
            with workspace_lock(clone_path):
                prepare_workspace(clone_path)
                fetch_origin(clone_path)
                store = get_context_store()
                store.load()
                crew_context = store.get_summary(exclude="merge")
                logger.info("[%s] context from previous crews (%d chars)", TAG, len(crew_context))
                logger.info("[%s] starting", TAG)
                result = MergeCrew.kickoff(
                    repo_config=repo_config,
                    clone_path=clone_path,
                    crew_context=crew_context,
                )
                store.add("merge", str(result))
                elapsed = time.monotonic() - t0
                logger.info("[%s] done | repo: %s | elapsed: %.1fs", TAG, repo_config.repo, elapsed)
        except TimeoutError as exc:
            logger.info("[%s] Skipping - shared clone is busy: %s", TAG, exc)
        except Exception as e:
            logger.exception("[%s] failed: %s", TAG, e)
        finally:
            try:
                cleanup_workspace(clone_path)
            except Exception as cleanup_exc:
                logger.warning("[%s] cleanup failed: %s", TAG, cleanup_exc)
        _log_next_run(TAG)

    run_if_tokens_available(_run)


# QA Crew disabled - automation infra to be added later
# def run_qa_crew_job() -> None: ...
