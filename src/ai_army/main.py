"""AI-Army entry point - scheduler and CLI."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from ai_army.logging_config import configure_logging

load_dotenv(os.getenv("ENV_FILE", ".env"))

logger = logging.getLogger(__name__)


def run_product_crew():
    """Run Product Crew once (no scheduler)."""
    from ai_army.config import get_github_repos
    from ai_army.crews.product_crew import ProductCrew
    from ai_army.memory.context_store import get_context_store
    from ai_army.tools.github_tools import check_github_connection_and_log

    repos = get_github_repos()
    if not repos:
        logger.warning("Product Crew: no GitHub repos configured")
    else:
        logger.info("GitHub repos: %s", ", ".join(r.repo for r in repos))
        check_github_connection_and_log(repos)
    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="product")
    if crew_context:
        logger.info("Product Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting Product Crew (PM + Product Agent)")
    result = ProductCrew.kickoff(crew_context=crew_context)
    store.add("product", result)
    logger.info("Product Crew finished (result len=%d)", len(str(result)))
    return result


def run_team_lead_crew():
    """Run Team Lead Crew once."""
    from ai_army.crews.team_lead_crew import TeamLeadCrew
    from ai_army.memory.context_store import get_context_store

    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="team_lead")
    if crew_context:
        logger.info("Team Lead Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting Team Lead Crew")
    result = TeamLeadCrew.kickoff(crew_context=crew_context)
    store.add("team_lead", result)
    logger.info("Team Lead Crew finished (result len=%d)", len(str(result)))
    return result


def run_dev_crew(agent_type: str):
    """Run Development Crew once."""
    from ai_army.crews.dev_crew import DevCrew
    from ai_army.memory.context_store import get_context_store

    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="dev")
    if crew_context:
        logger.info("Dev Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting Dev Crew (agent: %s)", agent_type)
    result = DevCrew.kickoff(agent_type=agent_type, crew_context=crew_context)
    store.add("dev", result)
    logger.info("Dev Crew finished (result len=%d)", len(str(result)))
    return result


def run_qa_crew():
    """Run QA Crew once."""
    from ai_army.crews.qa_crew import QACrew
    from ai_army.memory.context_store import get_context_store

    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="qa")
    if crew_context:
        logger.info("QA Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting QA Crew")
    result = QACrew.kickoff(crew_context=crew_context)
    store.add("qa", result)
    logger.info("QA Crew finished (result len=%d)", len(str(result)))
    return result


def run_scheduler():
    """Run the scheduler: Product → Team Lead → Dev (frontend/backend/fullstack) → QA, hourly pipeline."""
    configure_logging()
    from ai_army.scheduler.runner import start_scheduler
    scheduler = start_scheduler()
    logger.info("Scheduler running. Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI-Army: Multi-agent orchestration for GitHub-driven development"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # schedule - run scheduler (default)
    subparsers.add_parser("schedule", help="Run scheduler (Product → Team Lead → Dev → QA pipeline)")

    # product - run Product Crew once
    subparsers.add_parser("product", help="Run Product Crew once")

    # team-lead - run Team Lead Crew once
    subparsers.add_parser("team-lead", help="Run Team Lead Crew once")

    # dev - run Development Crew once
    dev_parser = subparsers.add_parser("dev", help="Run Development Crew once")
    dev_parser.add_argument(
        "--type",
        choices=["frontend", "backend", "fullstack"],
        default="frontend",
        help="Agent type",
    )

    # qa - run QA Crew once
    subparsers.add_parser("qa", help="Run QA Crew once")

    args = parser.parse_args()

    configure_logging()

    if args.command == "schedule" or args.command is None:
        logger.info("Running scheduler (default command)")
        run_scheduler()
    elif args.command == "product":
        result = run_product_crew()
        print(result)
    elif args.command == "team-lead":
        result = run_team_lead_crew()
        print(result)
    elif args.command == "dev":
        result = run_dev_crew(agent_type=getattr(args, "type", "frontend"))
        print(result)
    elif args.command == "qa":
        result = run_qa_crew()
        print(result)
    else:
        logger.debug("No command specified, showing help")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
