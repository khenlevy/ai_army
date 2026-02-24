# Configuration Reference

Environment variables used by AI-Army. Source: [src/ai_army/config/settings.py](src/ai_army/config/settings.py), [.env.example](.env.example), [main.py](src/ai_army/main.py).

## Environment Variables

| Env Var | Description | Default | Used By |
|---------|-------------|---------|---------|
| ANTHROPIC_API_KEY | Claude API key (required) | (none) | All crews |
| GITHUB_TARGET_TOKEN | GitHub PAT for single repo | "" | GitHub tools (fallback) |
| GITHUB_TARGET_REPO | owner/repo for single repo | "" | GitHub tools |
| GITHUB_REPO_N, GITHUB_TOKEN_N | Multi-repo (N=1,2,...) | (none) | get_github_repos() |
| REPO_WORKSPACE | Dev clone + context/index base | .ai_army_workspace in cwd | context_store, indexer, search, repo_clone |
| LOCAL_REPO_PATH | Override for git ops (dev crew) | "" | git_tools |
| RAG_EMBEDDING_MODEL | sentence-transformers model ID | all-MiniLM-L6-v2 | indexer, search |
| ENV_FILE | Dotenv file path | .env | main.py load_dotenv, settings |
| LANGCHAIN_TRACING_V2 | Enable LangSmith tracing | (none) | LangChain |
| LANGCHAIN_API_KEY | LangSmith API key | (none) | LangChain |
| GITHUB_TOKEN_SELF | PAT for GHCR push (deploy) | (none) | release script (README) |

## Single vs Multi-Repo

- **Single repo:** Set `GITHUB_TARGET_TOKEN` and `GITHUB_TARGET_REPO`
- **Multi-repo:** Set `GITHUB_REPO_1`, `GITHUB_TOKEN_1`, `GITHUB_REPO_2`, `GITHUB_TOKEN_2`, etc. (numbered pairs)
