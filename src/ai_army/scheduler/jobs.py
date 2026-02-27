"""Scheduled jobs - Product, Team Lead, Dev crews with token check and context store.

Team Lead and Dev use GitHub-only pre-checks before invoking Claude.
QA is disabled (automation infra to be added later).
"""

import logging

from ai_army.config import get_github_repos
from ai_army.crews.dev_crew import DevCrew
from ai_army.crews.product_crew import ProductCrew
from ai_army.crews.team_lead_crew import TeamLeadCrew
from ai_army.memory.context_store import get_context_store
from ai_army.scheduler.token_check import run_if_tokens_available
from ai_army.tools.github_helpers import (
    count_issues_for_dev,
    count_issues_ready_for_breakdown,
    list_issues_for_dev,
)

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


def run_product_crew_job() -> None:
    """Run Product Crew for each configured repo. Skips when API limit reached."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return

    def _run() -> None:
        store = get_context_store()
        store.load()
        crew_context = store.get_summary(exclude="product")
        logger.info("Product Crew: context from previous crews (%d chars)", len(crew_context))
        logger.info("GitHub repos for this run: %s", ", ".join(r.repo for r in repos))
        for repo_config in repos:
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
    """Run Team Lead Crew: break down ready-for-breakdown issues into sub-issues (frontend/backend/fullstack).
    Uses GitHub-only pre-check: skip Claude if no issues need breaking down."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return

    # GitHub-only pre-check: no Claude if no work
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
    """Run Dev Crew for one agent type (frontend, backend, fullstack). Picks issues with matching label, not in-progress/in-review.
    Uses GitHub-only pre-check: skip Claude if no issues available for this agent type."""

    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return

    # GitHub-only pre-check: no Claude if no work
    count = count_issues_for_dev(repos[0], agent_type)
    if count == 0:
        logger.info("Dev Crew (%s): no available issues (without in-progress/in-review), skipping", agent_type)
        _log_next_run(f"dev_crew_{agent_type}")
        return

    def _run() -> None:
        store = get_context_store()
        store.load()
        in_progress_count = sum(
            1 for _, _, is_in_progress in list_issues_for_dev(repos[0], agent_type)
            if is_in_progress
        )
        crew_context = (
            store.get_summary(exclude=None)
            if in_progress_count > 0
            else store.get_summary(exclude="dev")
        )
        logger.info("Dev Crew (%s): context from previous crews (%d chars)", agent_type, len(crew_context))
        try:
            logger.info("Dev Crew (%s) starting (%d issues available)", agent_type, count)
            result = DevCrew.kickoff(agent_type=agent_type, crew_context=crew_context)
            store.add("dev", str(result))
            logger.info("Dev Crew (%s) done successfully", agent_type)
        except Exception as e:
            logger.exception("Dev Crew (%s) failed: %s", agent_type, e)
        _log_next_run(f"dev_crew_{agent_type}")

    run_if_tokens_available(_run)


# QA Crew disabled - automation infra to be added later
# def run_qa_crew_job() -> None: ...
