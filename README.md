# AI-Army

Multi-agent orchestration with CrewAI for GitHub-driven development workflow. All agents use the GitHub integration layer. Product team creates and prioritizes issues with lifecycle labels; Team Lead breaks features down before developers take them; dev agents implement and QA merges.

## Architecture

- **Product Crew**: Product Manager + Product Agent create/prioritize issues with labels
- **Team Lead Crew**: Breaks features into sub-tasks (frontend, backend, fullstack)
- **Development Crew**: Front-end, Server-side, Full-stack agents pick up sub-tasks and submit PRs
- **QA Crew**: Reviews PRs, runs tests, merges when passing

## Issue Lifecycle Labels

| Label | Meaning |
|-------|---------|
| `backlog` | In product backlog, not yet prioritized |
| `prioritized` | PM has prioritized; ready for Product Agent |
| `ready-for-breakdown` | Product Agent enriched; ready for Team Lead |
| `broken-down` | Team Lead created sub-tasks; parent is decomposed |
| `frontend` / `backend` / `fullstack` | Sub-task type for dev agent assignment |
| `in-progress` | Dev agent is working on it |
| `in-review` | PR opened, awaiting QA |
| `done` | Merged and closed |

## Setup

### 1. Install dependencies

With Poetry (recommended):

```bash
poetry install
```

Or with pip:

```bash
pip install -e .
```

### 2. Environment variables

Copy `.env.example` to `.env` (development) and `.env.production` (production):

```bash
cp .env.example .env
cp .env.example .env.production
```

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude (required) |
| `GITHUB_TOKEN` | GitHub token (single repo) |
| `GITHUB_TARGET_REPO` | Target repo `owner/repo` (single repo) |
| `GITHUB_REPO_1`, `GITHUB_TOKEN_1` | First repo (multi-repo) |
| `GITHUB_REPO_2`, `GITHUB_TOKEN_2` | Second repo (multi-repo) |
| ... | Add more as needed |
| `LOCAL_REPO_PATH` | Path to a cloned repo for dev crew (branch, commit, push). Remote must be configured. |

### 3. Create labels in your GitHub repo

Ensure these labels exist in your target repository:

- `backlog`, `prioritized`, `ready-for-breakdown`, `broken-down`
- `frontend`, `backend`, `fullstack`
- `in-progress`, `in-review`, `done`
- `bug`, `feature` (optional)

### 4. Product Crew context (optional but recommended)

The Product Manager and Product Agent are guided by:

- **Project README** – Fetched from the target repo; their work is aligned with it.
- **Product Overview** and **Product Goal** – Set in `src/ai_army/config/product_context.yaml`. Edit these for your project so prioritization and enrichment match your vision.

**Open issue cap:** No more than 8 open issues are allowed. When the count reaches 8 (from any source), the app logs to the console and the PM is instructed not to create new issues until the count is below the cap.

## Run

### Start script (default: .env)

```bash
python scripts/start.py                    # dev (.env)
ENV_FILE=.env.production python scripts/start.py   # prod
python scripts/start.py --env .env.production product   # run product crew with prod env
```

### Scheduler (Product Crew every hour)

Runs Product Crew for each configured repo. Skips when API rate limit (429) is reached.

- **Startup check**: Verifies API capacity and repo config before starting
- **Per-run check**: Before each job, checks API availability; skips silently if limit reached

```bash
poetry run ai-army schedule
# or (if installed)
ai-army schedule
```

### Run crews once

```bash
# Product Crew - create/prioritize issues
poetry run ai-army product

# Team Lead Crew - break features into sub-tasks
poetry run ai-army team-lead

# Development Crew (frontend, backend, or fullstack)
poetry run ai-army dev --type frontend
poetry run ai-army dev --type backend
poetry run ai-army dev --type fullstack

# QA Crew - review and merge PRs
poetry run ai-army qa
```

### Release

```bash
# Create git tag for current version (e.g. v0.1.0)
python scripts/release.py

# Create tag and deploy to droplet (ssh ai-army-droplet)
python scripts/release.py --deploy

# Dry run - show commands without executing
python scripts/release.py --dry-run
python scripts/release.py --deploy --dry-run
```

Set `RELEASE_APP_PATH` to override the app path on the droplet (default: `~/ai_army`). On deploy, the script copies `.env.production` to `.env` on the droplet so the app uses production config.

### Docker

The image entrypoint copies `.env.production` to `.env` at container start when present (so the app loads prod config). Provide production env by mounting the file or using `--env-file`:

```bash
# Build image
docker build -t ai-army:latest .

# Run: mount .env.production so entrypoint copies it to .env for the app
docker run -v $(pwd)/.env.production:/app/.env.production ai-army:latest

# Or pass vars directly (no file in container; entrypoint then leaves .env unchanged)
docker run --env-file .env.production ai-army:latest
```

## Workflow

1. **Scheduler** runs Product Crew hourly (or run `ai-army product` manually)
2. **Product Crew** creates/updates issues with `backlog` / `prioritized` labels
3. **Product Agent** enriches issues, sets `ready-for-breakdown`
4. **Team Lead** runs (`ai-army team-lead`): breaks features into sub-issues with `frontend`/`backend`/`fullstack`
5. **Dev Crew** runs (`ai-army dev --type X`): picks up sub-tasks, implements, opens PRs
6. **QA Crew** runs (`ai-army qa`): reviews PRs, merges when passing

## Project structure

```
ai_army/
├── pyproject.toml
├── poetry.lock
├── .env.example
├── scripts/
│   ├── start.py         # Start app (default .env)
│   └── release.py       # Create git tag, optionally deploy to ai-army-droplet
├── src/ai_army/
│   ├── config/
│   │   ├── settings.py
│   │   └── agents.yaml
│   ├── crews/
│   │   ├── product_crew.py
│   │   ├── team_lead_crew.py
│   │   ├── dev_crew.py
│   │   └── qa_crew.py
│   ├── tools/
│   │   └── github_tools.py
│   ├── scheduler/
│   │   ├── runner.py      # APScheduler setup
│   │   ├── jobs.py        # Product Crew job
│   │   └── token_check.py # API availability check
│   └── main.py
└── tests/
```

## Tech stack

- **Python** 3.10+
- **CrewAI** - agent orchestration
- **LangChain** - reasoning (via CrewAI)
- **PyGithub** - GitHub API
- **APScheduler** - hourly scheduling
- **Anthropic Claude** - LLM
