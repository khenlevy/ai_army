# Production – SSH, Logs, Release

## SSH to Production

Connect to the droplet (configure `~/.ssh/config` with host `ai-army-droplet`):

```bash
ssh ai-army-droplet
```

Or with explicit host if configured elsewhere:

```bash
ssh root@<droplet-ip>
```

## Searching Logs

Once connected (or via `ssh ai-army-droplet "..."`):

```bash
# Last 100 lines
sudo docker logs ai-army --tail 100

# Follow live
sudo docker logs ai-army -f

# Search for errors
sudo docker logs ai-army 2>&1 | grep -i error

# Search for exceptions
sudo docker logs ai-army 2>&1 | grep -i exception

# Last 500 lines, filter errors
sudo docker logs ai-army --tail 500 2>&1 | grep -iE "error|exception|failed"
```

## Release Pipeline

Run from repo root:

```bash
poetry run python scripts/release.py
```

**Steps (9 total):**

| Step | Action |
|------|--------|
| 1 | Version bump (`poetry version patch`), retag previous image |
| 2 | Git commit + push |
| 3 | Check Docker running locally |
| 4 | Build image (`ai-army:latest`) |
| 5 | Save to compressed tar (`dist/ai-army-{version}.tar.gz`) |
| 6 | Ensure prerequisites on droplet |
| 7 | SCP tar to droplet |
| 8 | SCP `.env.production` to droplet |
| 9 | Pre-deploy cleanup, stop/rm container, load image, run |

**Flags:**

- `--no-bump` – Skip version bump (retry after build failure)
- `--dry-run` – Print commands without executing

**Post-release:** Local tar is removed; Docker prune runs to free disk.
