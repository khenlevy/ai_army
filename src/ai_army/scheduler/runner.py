"""Scheduler runner - hourly Product Crew with startup check."""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.config import get_github_repos
from ai_army.scheduler.jobs import run_product_crew_job
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
        logger.error("Startup failed: no GitHub repos (GITHUB_TOKEN/GITHUB_TARGET_REPO or GITHUB_REPO_N/GITHUB_TOKEN_N)")
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
    """Create and configure the scheduler."""
    from ai_army.scheduler.jobs import set_scheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_product_crew_job,
        trigger="cron",
        hour="*",  # Every hour
        id="product_crew",
    )
    # Run Product Crew once at startup (as if schedule just arrived)
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
    job = scheduler.get_job("product_crew")
    if job and job.next_run_time:
        logger.info("Next run: %s", job.next_run_time.strftime("%Y-%m-%d %H:%M"))
    logger.info("Product Crew will run once at startup, then every hour.")
    return scheduler
