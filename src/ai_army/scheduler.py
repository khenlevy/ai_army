"""APScheduler setup for hourly Product Crew execution."""

from apscheduler.schedulers.background import BackgroundScheduler

from ai_army.crews.product_crew import ProductCrew


def _run_product_crew():
    """Job: trigger Product Crew kickoff."""
    try:
        ProductCrew.kickoff()
    except Exception as e:
        print(f"Product Crew job failed: {e}")


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the scheduler."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_product_crew,
        trigger="cron",
        hour="*",  # Every hour
        id="product_crew",
    )
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the scheduler. Call from main."""
    scheduler = create_scheduler()
    scheduler.start()
    return scheduler
