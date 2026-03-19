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
    from ai_army.rag.runtime_state import load_runtime_state, repo_key_for_config
    from ai_army.tools.github_tools import check_github_connection_and_log

    repos = get_github_repos()
    repo_config = repos[0] if repos else None
    repo_path = None
    if repo_config:
        state = load_runtime_state(repo_key_for_config(repo_config))
        repo_path = state.repo_path if state else None
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
    result = ProductCrew.kickoff(
        repo_config=repo_config,
        crew_context=crew_context,
        repo_path=repo_path,
    )
    store.add("product", str(result))
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
    store.add("team_lead", str(result))
    logger.info("Team Lead Crew finished (result len=%d)", len(str(result)))
    return result


def run_dev_crew(agent_type: str):
    """Run Development Crew once."""
    from ai_army.config import get_github_repos
    from ai_army.crews.dev_crew import DevCrew
    from ai_army.memory.context_store import get_context_store
    from ai_army.repo_clone import ensure_repo_cloned
    from ai_army.workspace_manager import workspace_lock

    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="dev")
    if crew_context:
        logger.info("Dev Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting Dev Crew (agent: %s)", agent_type)
    repos = get_github_repos()
    if repos:
        clone_path = ensure_repo_cloned(repos[0])
        if clone_path:
            with workspace_lock(clone_path):
                result = DevCrew.kickoff(agent_type=agent_type, crew_context=crew_context)
        else:
            result = DevCrew.kickoff(agent_type=agent_type, crew_context=crew_context)
    else:
        result = DevCrew.kickoff(agent_type=agent_type, crew_context=crew_context)
    store.add("dev", str(result))
    logger.info("Dev Crew finished (result len=%d)", len(str(result)))
    return result


def run_merge_crew():
    """Run Merge Crew once."""
    from ai_army.config import get_github_repos
    from ai_army.crews.merge_crew import MergeCrew
    from ai_army.memory.context_store import get_context_store
    from ai_army.repo_clone import ensure_repo_cloned
    from ai_army.workspace_manager import cleanup_workspace, fetch_origin, prepare_workspace, workspace_lock

    store = get_context_store()
    store.load()
    crew_context = store.get_summary(exclude="merge")
    if crew_context:
        logger.info("Merge Crew: using context from previous crews (%d chars)", len(crew_context))
    logger.info("Starting Merge Crew")
    repos = get_github_repos()
    if repos:
        clone_path = ensure_repo_cloned(repos[0])
        if clone_path:
            try:
                with workspace_lock(clone_path):
                    prepare_workspace(clone_path)
                    fetch_origin(clone_path)
                    result = MergeCrew.kickoff(
                        repo_config=repos[0],
                        clone_path=clone_path,
                        crew_context=crew_context,
                    )
            finally:
                try:
                    cleanup_workspace(clone_path)
                except Exception as exc:
                    logger.warning("Merge Crew cleanup failed: %s", exc)
        else:
            result = MergeCrew.kickoff(repo_config=repos[0], crew_context=crew_context)
    else:
        result = MergeCrew.kickoff(crew_context=crew_context)
    store.add("merge", str(result))
    logger.info("Merge Crew finished (result len=%d)", len(str(result)))
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
    store.add("qa", str(result))
    logger.info("QA Crew finished (result len=%d)", len(str(result)))
    return result


def run_check():
    """Print pipeline state: issue counts, labels, why crews skip."""
    from ai_army.config import get_github_repos
    from ai_army.tools.github_helpers import (
        count_backlog_promotable,
        count_issues_for_dev,
        count_issues_ready_for_breakdown,
        count_prioritized_needing_enrichment,
        get_open_issue_count,
        get_repo_from_config,
    )

    configure_logging()
    repos = get_github_repos()
    if not repos:
        print("No GitHub repos configured")
        return
    repo_config = repos[0]
    repo = get_repo_from_config(repo_config)
    open_count = get_open_issue_count(repo)
    prioritized_needing = count_prioritized_needing_enrichment(repo_config)
    backlog_promotable = count_backlog_promotable(repo_config)
    ready_for_breakdown = count_issues_ready_for_breakdown(repo_config)
    dev_frontend = count_issues_for_dev(repo_config, "frontend")
    dev_backend = count_issues_for_dev(repo_config, "backend")
    dev_fullstack = count_issues_for_dev(repo_config, "fullstack")
    open_prs = len(list(repo.get_pulls(state="open")))

    print(f"Repo: {repo_config.repo}")
    print(f"Open issues (excl PRs): {open_count}")
    print(f"Open PRs: {open_prs}")
    print()
    print("Pipeline:")
    print(f"  Product: prioritized needing enrichment = {prioritized_needing}")
    print(f"  Product: backlog/feature promotable to prioritized = {backlog_promotable}")
    print(f"  Team Lead: ready-for-breakdown (no broken-down) = {ready_for_breakdown}")
    print(f"  Dev frontend: {dev_frontend} | backend: {dev_backend} | fullstack: {dev_fullstack}")
    print()
    print("Labels required:")
    print("  Product: issues with 'prioritized' but not 'ready-for-breakdown'")
    print("  Team Lead: issues with 'ready-for-breakdown' but not 'broken-down'")
    print("  Dev: sub-issues with 'frontend'|'backend'|'fullstack' (created by Team Lead)")


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

    # merge - run Merge Crew once
    subparsers.add_parser("merge", help="Run Merge Crew once (merge PRs, resolve conflicts)")

    # qa - run QA Crew once
    subparsers.add_parser("qa", help="Run QA Crew once")

    # check - print pipeline state (issue counts, why crews skip)
    subparsers.add_parser("check", help="Print pipeline state: issue counts, labels")

    args = parser.parse_args()

    configure_logging()
    from ai_army.rag.search import log_rag_status
    log_rag_status()

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
    elif args.command == "merge":
        result = run_merge_crew()
        print(result)
    elif args.command == "qa":
        result = run_qa_crew()
        print(result)
    elif args.command == "check":
        run_check()
    else:
        logger.debug("No command specified, showing help")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
