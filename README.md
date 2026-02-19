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

```bash
pip install -e .
```

Or with uv:

```bash
uv pip install -e .
```

### 2. Environment variables

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude (required) |
| `GITHUB_TOKEN` | GitHub Personal Access Token (repo, issues, pull_requests scopes) |
| `GITHUB_TARGET_REPO` | Target repo in `owner/repo` format |

### 3. Create labels in your GitHub repo

Ensure these labels exist in your target repository:

- `backlog`, `prioritized`, `ready-for-breakdown`, `broken-down`
- `frontend`, `backend`, `fullstack`
- `in-progress`, `in-review`, `done`
- `bug`, `feature` (optional)

## Run

### Scheduler (Product Crew every hour)

```bash
ai-army schedule
# or
python -m ai_army schedule
```

### Run crews once

```bash
# Product Crew - create/prioritize issues
ai-army product

# Team Lead Crew - break features into sub-tasks
ai-army team-lead

# Development Crew (frontend, backend, or fullstack)
ai-army dev --type frontend
ai-army dev --type backend
ai-army dev --type fullstack

# QA Crew - review and merge PRs
ai-army qa
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
├── .env.example
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
│   ├── scheduler.py
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
