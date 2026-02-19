"""AI-Army entry point - scheduler and CLI."""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.getenv("ENV_FILE", ".env"))


def run_product_crew():
    """Run Product Crew once (no scheduler)."""
    from ai_army.crews.product_crew import ProductCrew
    return ProductCrew.kickoff()


def run_team_lead_crew():
    """Run Team Lead Crew once."""
    from ai_army.crews.team_lead_crew import TeamLeadCrew
    return TeamLeadCrew.kickoff()


def run_dev_crew(agent_type: str):
    """Run Development Crew once."""
    from ai_army.crews.dev_crew import DevCrew
    return DevCrew.kickoff(agent_type=agent_type)


def run_qa_crew():
    """Run QA Crew once."""
    from ai_army.crews.qa_crew import QACrew
    return QACrew.kickoff()


def run_scheduler():
    """Run the hourly scheduler (Product Crew)."""
    from ai_army.scheduler import start_scheduler
    scheduler = start_scheduler()
    print("Scheduler started. Product Crew will run every hour. Press Ctrl+C to exit.")
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("Scheduler stopped.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI-Army: Multi-agent orchestration for GitHub-driven development"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # schedule - run scheduler (default)
    subparsers.add_parser("schedule", help="Run hourly scheduler (Product Crew)")

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

    if args.command == "schedule" or args.command is None:
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
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
