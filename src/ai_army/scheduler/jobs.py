"""Scheduled jobs - Product Crew per repo, with token check."""

import logging

from ai_army.config import get_github_repos
from ai_army.crews.product_crew import ProductCrew
from ai_army.scheduler.token_check import run_if_tokens_available

logger = logging.getLogger(__name__)

_scheduler = None


def set_scheduler(scheduler) -> None:
    """Store scheduler ref for logging next run."""
    global _scheduler
    _scheduler = scheduler


def run_product_crew_job() -> None:
    """Run Product Crew for each configured repo. Skips when API limit reached."""
    repos = get_github_repos()
    if not repos:
        logger.warning("No GitHub repos configured, skipping job")
        return

    def _run() -> None:
        logger.info("GitHub repos for this run: %s", ", ".join(r.repo for r in repos))
        for repo_config in repos:
            try:
                logger.info("Product Crew starting | repo: %s", repo_config.repo)
                ProductCrew.kickoff(repo_config=repo_config)
                logger.info("Product Crew done successfully | repo: %s", repo_config.repo)
            except Exception as e:
                logger.exception("Product Crew failed | repo: %s | %s", repo_config.repo, e)
        # Log next run
        if _scheduler:
            job = _scheduler.get_job("product_crew")
            if job and job.next_run_time:
                logger.info("Next run: %s", job.next_run_time.strftime("%Y-%m-%d %H:%M"))

    run_if_tokens_available(_run)
