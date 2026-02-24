# AI-Army

Multi-agent orchestration for GitHub-driven development. Crews create issues, break them down, implement, and merge PRs—all via GitHub labels and API.

## Design

**Orchestration:** CrewAI runs agents; LangChain powers structured output and RAG. Crews run sequentially (Product → Team Lead → Dev → QA) via CLI or scheduler. Cross-crew memory (file-based) passes context between runs.

**GitHub:** Single integration layer. Issues move through lifecycle labels; PRs link via `Closes #N`. Supports single or multi-repo.

**Agents:**

| Crew | Agents | Role |
|------|--------|------|
| Product | PM, Product Agent | Create/prioritize issues; enrich with acceptance criteria |
| Team Lead | Team Lead | Break features into frontend/backend/fullstack sub-tasks |
| Dev | Frontend, Backend, Fullstack | Pick sub-tasks, implement, open PRs |
| QA | Automation Engineer | Review PRs, merge or request changes |

**LangChain:** Structured output (`with_structured_output`) for Product (issue creation), Team Lead (breakdown), QA (review). RAG retriever wraps codebase search. Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` for LangSmith traces.

## Labels

`backlog` → `prioritized` → `ready-for-breakdown` → `broken-down` → `frontend`/`backend`/`fullstack` → `in-progress` → `in-review` → `done`

**Scheduler (hourly pipeline):** Product (:00) → Team Lead (:10) → Dev frontend (:20) backend (:30) fullstack (:40) → QA (:50). Label-based: each dev agent picks only its label; `in-progress` claims an issue to avoid overlap.

Create these in your GitHub repo before use.

## Setup

```bash
poetry install
cp .env.example .env
```

Set `ANTHROPIC_API_KEY`, `GITHUB_TARGET_TOKEN`, `GITHUB_TARGET_REPO` (or `GITHUB_REPO_1`/`GITHUB_TOKEN_1` for multi-repo). Optional: `product_context.yaml` (Product Crew); `LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY` (LangSmith); `REPO_WORKSPACE` (dev clone path). Product Crew caps at 8 open issues.

## Run

```bash
poetry run ai-army schedule    # Product Crew hourly
poetry run ai-army product     # Product Crew once
poetry run ai-army team-lead   # Team Lead once
poetry run ai-army dev --type frontend
poetry run ai-army qa
```

## Deploy

```bash
python scripts/release.py   # Deploy current code to droplet
```

Requires `GITHUB_TOKEN_SELF` (or `GITHUB_TARGET_TOKEN`) in `.env.production` with `write:packages` scope for GHCR push.

## Tech

CrewAI, LangChain, PyGithub, Anthropic Claude, APScheduler, ChromaDB (RAG).
