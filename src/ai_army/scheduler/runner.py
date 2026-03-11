"""Scheduler runner - full pipeline: Product → Team Lead → Dev (frontend/backend/fullstack).

Schedule staggered to avoid blocking:
- Product (min 0): backlog → prioritized → ready-for-breakdown
- Team Lead (min 10): ready-for-breakdown → sub-issues with frontend/backend/fullstack (GitHub pre-check)
- Dev frontend (min 20), backend (min 30), fullstack (min 40): each picks own label (GitHub pre-check)
- QA disabled (automation infra to be added later)
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import partial

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.config import get_github_repos
from ai_army.config.settings import settings
from ai_army.scheduler.jobs import (
    run_rag_refresh_job,
    run_dev_crew_job,
    run_product_crew_job,
    run_team_lead_crew_job,
    set_scheduler,
)
from ai_army.scheduler.token_check import has_available_tokens
from ai_army.tools.github_tools import check_github_connection_and_log

logger = logging.getLogger(__name__)


def _minute_slot(offset_minutes: int) -> int:
    """Return the minute slot within the hour for a configured refresh window."""
    minute = settings.rag_refresh_minute + offset_minutes
    if minute > 59:
        raise ValueError(
            "RAG schedule exceeds the hour boundary. Reduce RAG_AGENT_WINDOW_DELAY_MINUTES "
            "or move RAG_REFRESH_MINUTE earlier."
        )
    return minute


def _refresh_hour_expr() -> str:
    interval = max(settings.rag_refresh_interval_hours, 1)
    return "*" if interval == 1 else f"*/{interval}"


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
    refresh_minute = _minute_slot(0)
    product_minute = _minute_slot(settings.rag_agent_window_delay_minutes)
    team_lead_minute = _minute_slot(settings.rag_agent_window_delay_minutes + 10)
    frontend_minute = _minute_slot(settings.rag_agent_window_delay_minutes + 20)
    backend_minute = _minute_slot(settings.rag_agent_window_delay_minutes + 30)
    fullstack_minute = _minute_slot(settings.rag_agent_window_delay_minutes + 40)

    scheduler.add_job(
        run_rag_refresh_job,
        trigger="cron",
        minute=str(refresh_minute),
        hour=_refresh_hour_expr(),
        id="rag_refresh",
    )
    # Product: runs after refresh window opens and can create/enrich issues.
    scheduler.add_job(
        run_product_crew_job,
        trigger="cron",
        minute=str(product_minute),
        hour=_refresh_hour_expr(),
        id="product_crew",
    )
    # Team Lead: breaks down sub-issues after the product window.
    scheduler.add_job(
        run_team_lead_crew_job,
        trigger="cron",
        minute=str(team_lead_minute),
        hour=_refresh_hour_expr(),
        id="team_lead_crew",
    )
    # Dev: runs only after refresh + readiness window.
    scheduler.add_job(
        partial(run_dev_crew_job, "frontend"),
        trigger="cron",
        minute=str(frontend_minute),
        hour=_refresh_hour_expr(),
        id="dev_crew_frontend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "backend"),
        trigger="cron",
        minute=str(backend_minute),
        hour=_refresh_hour_expr(),
        id="dev_crew_backend",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "fullstack"),
        trigger="cron",
        minute=str(fullstack_minute),
        hour=_refresh_hour_expr(),
        id="dev_crew_fullstack",
    )
    # QA disabled - automation infra to be added later
    # Startup window: refresh first, then open agent jobs with the same offsets.
    now = datetime.now(timezone.utc)
    scheduler.add_job(
        run_rag_refresh_job,
        trigger="date",
        run_date=now,
        id="rag_refresh_startup",
    )
    scheduler.add_job(
        run_product_crew_job,
        trigger="date",
        run_date=now + timedelta(minutes=settings.rag_agent_window_delay_minutes),
        id="product_crew_startup",
    )
    scheduler.add_job(
        run_team_lead_crew_job,
        trigger="date",
        run_date=now + timedelta(minutes=settings.rag_agent_window_delay_minutes + 10),
        id="team_lead_crew_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "frontend"),
        trigger="date",
        run_date=now + timedelta(minutes=settings.rag_agent_window_delay_minutes + 20),
        id="dev_crew_frontend_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "backend"),
        trigger="date",
        run_date=now + timedelta(minutes=settings.rag_agent_window_delay_minutes + 30),
        id="dev_crew_backend_startup",
    )
    scheduler.add_job(
        partial(run_dev_crew_job, "fullstack"),
        trigger="date",
        run_date=now + timedelta(minutes=settings.rag_agent_window_delay_minutes + 40),
        id="dev_crew_fullstack_startup",
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
    logger.info(
        "Scheduler running. Pipeline: RAG refresh(:%02d) → Product(:%02d) → Team Lead(:%02d) → "
        "Dev frontend(:%02d) backend(:%02d) fullstack(:%02d). QA disabled.",
        _minute_slot(0),
        _minute_slot(settings.rag_agent_window_delay_minutes),
        _minute_slot(settings.rag_agent_window_delay_minutes + 10),
        _minute_slot(settings.rag_agent_window_delay_minutes + 20),
        _minute_slot(settings.rag_agent_window_delay_minutes + 30),
        _minute_slot(settings.rag_agent_window_delay_minutes + 40),
    )
    return scheduler
