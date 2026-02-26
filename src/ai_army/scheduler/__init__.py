"""Scheduler – hourly pipeline execution.

Jobs (runner.create_scheduler): product_crew (:00), team_lead_crew (:10), dev_crew_frontend (:20),
dev_crew_backend (:30), dev_crew_fullstack (:40). Product also runs once at startup.
Team Lead and Dev use GitHub-only pre-checks before invoking Claude. QA disabled.
Each job uses run_if_tokens_available (token_check) before running.
"""

from ai_army.scheduler.runner import start_scheduler

__all__ = ["start_scheduler"]
