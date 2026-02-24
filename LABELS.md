# Label Workflow Glossary

## Lifecycle

```
backlog → prioritized → ready-for-breakdown → broken-down → frontend/backend/fullstack → in-progress → in-review → done
```

Create these labels in your GitHub repo before use.

## Crew → Label Mapping

| Crew | Consumes | Adds |
|------|----------|------|
| **Product** | (all open issues) | backlog, prioritized; EnrichIssue adds ready-for-breakdown |
| **Team Lead** | ready-for-breakdown | broken-down (parent), frontend/backend/fullstack (sub-issues) |
| **Dev** | frontend, backend, or fullstack (excludes in-progress, in-review) | in-progress (when claiming), in-review (when PR opened) |
| **QA** | (via PR review) | done (when PR merged) |

## Sub-Issue Linking

- Sub-issues include `Parent: #N` in the body (added by BreakdownAndCreateSubIssuesTool)
- Parent issue gets a comment listing sub-issues and the `broken-down` label
- PRs link via `Closes #N` in the body; QA sets `done` on the linked issue when merging
