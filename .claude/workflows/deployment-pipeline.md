# Workflow: Deployment Pipeline

NanoClaw deployment process from code merge to production via docker-compose.

## Pipeline Overview

```
Code Merge to Main
    │
    ▼
[CI — GitHub Actions]
    ├── ruff lint
    ├── pytest (coverage gate 70%)
    ├── secret scan (trufflehog)
    └── Docker build + push to GHCR
         │ (manual trigger)
         ▼
[Production Server]
    docker compose pull
    docker compose up -d
    docker compose logs -f nanoclaw
```

## Stage 1: CI (Automated on every PR/merge)

Target: < 5 minutes.

```bash
# Runs automatically via .github/workflows/ci.yml
# 1. ruff check + ruff format --check
# 2. pytest tests/ --cov=. --cov-fail-under=70
# 3. trufflehog secret scan
# 4. docker build + push to ghcr.io (main branch only)
```

CI must pass before merging any PR. See `agents/infrastructure/cicd.md` for the full workflow YAML.

## Stage 2: Deploy to Production

After CI passes on main:

```bash
# SSH to production server
ssh user@server

cd /opt/nanoclaw
git pull
docker compose pull       # get latest GHCR image
docker compose up -d      # restart with new image
docker compose logs -f nanoclaw   # verify startup
```

**Verify the bot is healthy:**
- Bot comes online in Discord (green status)
- Send a test command (`@CTO status`) and verify response
- Check `docker compose logs` for any ERROR-level messages

## Post-Deploy Monitoring (10 minutes)

Watch for:
- Discord bot status: online
- No `ERROR` or `CRITICAL` log lines in `docker compose logs`
- Budget guard and rate limiter responding correctly
- `@CTO status` command returns expected output

## Rollback

```bash
# Option A: Roll back to previous image
docker compose down
# Edit docker-compose.yml image tag to previous SHA
docker compose up -d

# Option B: Roll back git + rebuild
git revert HEAD
git push  # triggers CI → new build → redeploy
```

## Hotfix Process

For SEV1/SEV2 bugs (bot down, security issue):

```bash
git checkout -b hotfix/description main
# fix + test
git push origin hotfix/description
# create PR → fast review → merge → CI → deploy
```

No staging environment for NanoClaw — deploy directly to production after CI passes.

## Deployment Constraints

- Never push directly to `main` without CI passing
- Never run `docker compose up` with a broken test suite
- Never deploy on a whim — verify CI is green first
- Before deploy: check `.env` is up to date on the server
- After deploy: verify `@CTO status` responds within 60 seconds
