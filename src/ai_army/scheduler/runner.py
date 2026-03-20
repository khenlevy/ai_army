"""Scheduler runner - full pipeline: Product → Team Lead → Dev (frontend/backend/fullstack).

Schedule aligned with RAG build time (~96 min). RAG runs at :00; crews run at :50-:59
after RAG finishes (~:36) and agent window opens (~:46). Big buffers for reliability.
- Product (:50), Team Lead (:52), Dev frontend (:54) backend (:56) fullstack (:58)
- Conflict check (:59), Merge agent (:02 next hour, after Dev releases workspace)
- QA disabled (automation infra to be added later)
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import partial

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.config import get_github_repos
from ai_army.config.settings import settings
from ai_army.scheduler.jobs import (
    run_conflict_check_job,
    run_merge_crew_job,
    run_rag_refresh_job,
    run_dev_crew_job,
    run_product_crew_job,
    run_team_lead_crew_job,
    set_scheduler,
)
from ai_army.scheduler.token_check import has_available_tokens
from ai_army.tools.github_tools import check_github_connection_and_log

logger = logging.getLogger(__name__)


def _hour_minute_slot(offset_minutes: int) -> tuple[int, int]:
    """Return the hour offset and minute slot for an offset from the refresh window."""
    total_minutes = settings.rag_refresh_minute + offset_minutes
    return divmod(total_minutes, 60)


def _minute_slot(offset_minutes: int) -> int:
    """Return the minute slot within the hour for a configured refresh window."""
    _, minute = _hour_minute_slot(offset_minutes)
    return minute


def _refresh_hour_expr(hour_offset: int = 0) -> str:
    interval = max(settings.rag_refresh_interval_hours, 1)
    if interval == 1:
        return "*"
    hours = [str(hour) for hour in range(hour_offset, 24, interval)]
    return ",".join(hours) if hours else str(hour_offset % 24)


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
    """Create and configure the scheduler with staggered pipeline.

    Crews run at :50-:59 to align with RAG finish (~:36) + agent window (~:46).
    RAG runs every 2h by default for big buffers.
    """
    scheduler = BackgroundScheduler()
    base = settings.rag_crew_base_minute
    product_minute = base
    team_lead_minute = base + 2
    frontend_minute = base + 4
    backend_minute = base + 6
    fullstack_minute = base + 8
    conflict_check_minute = base + 9
    # Merge runs at :02 next hour so Dev crews (:58) have released workspace lock
    merge_minute = 2

    refresh_minute = _minute_slot(0)
    refresh_hour_offset, _ = _hour_minute_slot(0)
    crew_hour = "*"  # Crews run every hour; _repo_ready skips when window closed

    scheduler.add_job(
        run_rag_refresh_job,
        trigger="cron",
        minute=str(refresh_minute),
        hour=_refresh_hour_expr(refresh_hour_offset),
        id="rag_refresh",
    )
    scheduler.add_job(
        run_product_crew_job,
        trigger="cron",
        minute=str(product_minute),
        hour=crew_hour,
        id="product_crew",
    )
    scheduler.add_job(
        run_team_lead_crew_job,
        trigger="cron",
        minute=str(team_lead_minute),
        hour=crew_hour,
        id="team_lead_crew",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "frontend"),
        trigger="cron",
        minute=str(frontend_minute),
        hour=crew_hour,
        id="dev_crew_frontend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "backend"),
        trigger="cron",
        minute=str(backend_minute),
        hour=crew_hour,
        id="dev_crew_backend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "fullstack"),
        trigger="cron",
        minute=str(fullstack_minute),
        hour=crew_hour,
        id="dev_crew_fullstack",
    )
    scheduler.add_job(
        run_conflict_check_job,
        trigger="cron",
        minute=str(conflict_check_minute),
        hour=crew_hour,
        id="conflict_check",
    )
    scheduler.add_job(
        run_merge_crew_job,
        trigger="cron",
        minute=str(merge_minute),
        hour=crew_hour,
        id="merge_crew",
    )
    # QA disabled - automation infra to be added later
    # Startup: RAG first; crews 100 min later (RAG ~96 min + buffer)
    now = datetime.now(timezone.utc)
    startup_delay = 100  # Minutes until first crew (RAG takes ~96 min)
    scheduler.add_job(
        run_rag_refresh_job,
        trigger="date",
        run_date=now,
        id="rag_refresh_startup",
    )
    scheduler.add_job(
        run_product_crew_job,
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay),
        id="product_crew_startup",
    )
    scheduler.add_job(
        run_team_lead_crew_job,
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 2),
        id="team_lead_crew_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "frontend"),
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 4),
        id="dev_crew_frontend_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "backend"),
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 6),
        id="dev_crew_backend_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "fullstack"),
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 8),
        id="dev_crew_fullstack_startup",
    )
    scheduler.add_job(
        run_conflict_check_job,
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 9),
        id="conflict_check_startup",
    )
    scheduler.add_job(
        run_merge_crew_job,
        trigger="date",
        run_date=now + timedelta(minutes=startup_delay + 9),
        id="merge_crew_startup",
    )
    set_scheduler(scheduler)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the scheduler. Runs startup check first."""
    _check_startup()
    from ai_army.rag.search import log_rag_status
    log_rag_status()
    scheduler = create_scheduler()
    scheduler.start()
    base = settings.rag_crew_base_minute
    logger.info(
        "Scheduler running. Pipeline: RAG refresh(:00 every %dh) → Product(:%02d) → Team Lead(:%02d) → "
        "Dev frontend(:%02d) backend(:%02d) fullstack(:%02d) → Conflict(:%02d) → Merge(:%02d). QA disabled.",
        settings.rag_refresh_interval_hours,
        base,
        base + 2,
        base + 4,
        base + 6,
        base + 8,
        base + 9,
        2,
    )
    return scheduler
