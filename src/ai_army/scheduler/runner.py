"""Scheduler runner - hourly Product Crew with startup check."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.config import get_github_repos
from ai_army.scheduler.jobs import run_product_crew_job
from ai_army.scheduler.token_check import has_available_tokens

logger = logging.getLogger(__name__)


def _check_startup() -> bool:
    """Verify API and repos on startup. Returns True if ready."""
    if not has_available_tokens():
        logger.error("Startup failed: API tokens/rate limit - jobs will skip until available")
        return False
    repos = get_github_repos()
    if not repos:
        logger.error("Startup failed: no GitHub repos (GITHUB_TOKEN/GITHUB_TARGET_REPO or GITHUB_REPO_N/GITHUB_TOKEN_N)")
        return False
    logger.info("Startup OK | %d repo(s)", len(repos))
    return True


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the scheduler."""
    from ai_army.scheduler.jobs import set_scheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_product_crew_job,
        trigger="cron",
        hour="*",  # Every hour
        id="product_crew",
    )
    set_scheduler(scheduler)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the scheduler. Runs startup check first."""
    _check_startup()
    scheduler = create_scheduler()
    scheduler.start()
    job = scheduler.get_job("product_crew")
    if job and job.next_run_time:
        logger.info("Next run: %s", job.next_run_time.strftime("%Y-%m-%d %H:%M"))
    return scheduler
