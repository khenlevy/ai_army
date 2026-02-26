"""Scheduler runner - full pipeline: Product → Team Lead → Dev (frontend/backend/fullstack).

Schedule staggered to avoid blocking:
- Product (min 0): backlog → prioritized → ready-for-breakdown
- Team Lead (min 10): ready-for-breakdown → sub-issues with frontend/backend/fullstack (GitHub pre-check)
- Dev frontend (min 20), backend (min 30), fullstack (min 40): each picks own label (GitHub pre-check)
- QA disabled (automation infra to be added later)
"""

import logging
from datetime import datetime, timezone
from functools import partial

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.config import get_github_repos
from ai_army.scheduler.jobs import (
    run_dev_crew_job,
    run_product_crew_job,
    run_team_lead_crew_job,
    set_scheduler,
)
from ai_army.scheduler.token_check import has_available_tokens
from ai_army.tools.github_tools import check_github_connection_and_log

logger = logging.getLogger(__name__)


def _check_startup() -> bool:
    """Verify API, GitHub, and repos on startup. Returns True if ready."""
    logger.info("Scheduler startup check...")
    if not has_available_tokens():
        logger.error("Startup failed: API tokens/rate limit - jobs will skip until available")
        return False
    repos = get_github_repos()
    if not repos:
        logger.error("Startup failed: no GitHub repos (GITHUB_TARGET_TOKEN/GITHUB_TARGET_REPO or GITHUB_REPO_N/GITHUB_TOKEN_N)")
        return False
    # Verify we can connect to GitHub and get each repo
    results = check_github_connection_and_log(repos)
    ok = [r.repo for r, success in results if success]
    failed = [r.repo for r, success in results if not success]
    if ok:
        logger.info("GitHub: able to connect and get repos | %s", ", ".join(ok))
    if failed:
        logger.warning("GitHub: failed to connect to repo(s) | %s", ", ".join(failed))
    logger.info("Startup OK | %d repo(s) configured", len(repos))
    return True


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the scheduler with staggered pipeline."""
    scheduler = BackgroundScheduler()
    # Product: min 0 - manages backlog, produces ready-for-breakdown
    scheduler.add_job(
        run_product_crew_job,
        trigger="cron",
        minute="0",
        hour="*",
        id="product_crew",
    )
    # Team Lead: min 10 - breaks down into frontend/backend/fullstack sub-issues
    scheduler.add_job(
        run_team_lead_crew_job,
        trigger="cron",
        minute="10",
        hour="*",
        id="team_lead_crew",
    )
    # Dev: min 20, 30, 40 - each agent type picks its label, adds in-progress when claiming
    scheduler.add_job(
        partial(run_dev_crew_job, "frontend"),
        trigger="cron",
        minute="20",
        hour="*",
        id="dev_crew_frontend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "backend"),
        trigger="cron",
        minute="30",
        hour="*",
        id="dev_crew_backend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "fullstack"),
        trigger="cron",
        minute="40",
        hour="*",
        id="dev_crew_fullstack",
    )
    # QA disabled - automation infra to be added later
    # Run Product once at startup
    scheduler.add_job(
        run_product_crew_job,
        trigger="date",
        run_date=datetime.now(timezone.utc),
        id="product_crew_startup",
    )
    set_scheduler(scheduler)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the scheduler. Runs startup check first."""
    _check_startup()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info(
        "Scheduler running. Pipeline: Product(:00) → Team Lead(:10) → Dev frontend(:20) backend(:30) fullstack(:40). QA disabled."
    )
    return scheduler
