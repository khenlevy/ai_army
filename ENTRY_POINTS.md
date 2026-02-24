# Entry Points – CLI and Scheduler

## CLI Commands (main.py)

| Command | Handler | Description |
|---------|---------|-------------|
| schedule (default) | run_scheduler() | Start hourly pipeline |
| product | run_product_crew() | Product Crew once |
| team-lead | run_team_lead_crew() | Team Lead Crew once |
| dev --type {frontend\|backend\|fullstack} | run_dev_crew(agent_type) | Dev Crew once |
| qa | run_qa_crew() | QA Crew once |

## Scheduler Jobs (runner.py, jobs.py)

| Job ID | Cron | Implementation |
|--------|------|----------------|
| product_crew | :00 hourly | run_product_crew_job |
| product_crew_startup | once at start | run_product_crew_job |
| team_lead_crew | :10 hourly | run_team_lead_crew_job |
| dev_crew_frontend | :20 hourly | run_dev_crew_job("frontend") |
| dev_crew_backend | :30 hourly | run_dev_crew_job("backend") |
| dev_crew_fullstack | :40 hourly | run_dev_crew_job("fullstack") |
| qa_crew | :50 hourly | run_qa_crew_job |
