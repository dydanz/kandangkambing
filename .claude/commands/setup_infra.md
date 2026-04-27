# /setup-infra

Sets up NanoClaw deployment infrastructure — Docker, docker-compose, `.env`, and GitHub Actions CI.

## When Invoked

```
What infrastructure would you like to set up?

1. Docker + docker-compose (new server deployment)
2. GitHub Actions CI (lint + test + build pipeline)
3. Environment configuration (.env + settings.json review)
4. Bot token setup (Discord developer portal guidance)

Specify what you need.
```

## Option 1: Docker Deployment

```
To deploy NanoClaw on a server:

Prerequisites on the server:
  - Docker 24+
  - docker-compose v2
  - git (to clone the repo)
  - gh CLI (authenticated, for PR creation)
  - claude CLI (authenticated, on PATH)

Steps:
  1. Clone the repo: git clone <repo> /opt/nanoclaw
  2. cd /opt/nanoclaw/nanoclaw
  3. cp .env.example .env && nano .env   # fill in all tokens
  4. Edit config/settings.docker.json:
     - project_path: /workspace/project  (mount target project here)
     - worktree_base: /workspace/worktrees
     - discord.allowed_user_ids: [your Discord user ID]
     - discord.command_channel_id, log_channel_id, commits_channel_id
  5. docker compose up -d
  6. docker compose logs -f nanoclaw   # verify startup
```

Volumes required in docker-compose.yml:
```yaml
volumes:
  - /path/to/target-project:/workspace/project
  - /path/to/worktrees:/workspace/worktrees
  - ./memory:/app/memory
```

## Option 2: GitHub Actions CI

See `.claude/agents/infrastructure/cicd.md` for the full CI workflow template.

Minimum required jobs: `lint`, `test`, `build`.

Secrets to configure in GitHub repository settings:
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY` — for SSH deploy (optional)

## Option 3: Environment Configuration

```
Required .env entries:
  DISCORD_BOT_TOKEN      — legacy fallback
  DISCORD_CTO_TOKEN      — CTO bot (listener)
  DISCORD_PMO_TOKEN      — PM bot
  DISCORD_SED_TOKEN      — Dev/SED bot
  DISCORD_QAD_TOKEN      — QA bot
  ANTHROPIC_API_KEY      — primary LLM
  OPENAI_API_KEY         — fallback LLM (optional)
  GOOGLE_API_KEY         — fallback LLM (optional)
  GITHUB_TOKEN           — PR creation

Check: none of these should appear in settings.json or any committed file.
```

## Option 4: Bot Token Setup

```
For each bot (CTO, PMO, SED, QAD):
  1. Go to https://discord.com/developers/applications
  2. Create New Application → name it (e.g., "NanoClaw CTO")
  3. Bot tab → Add Bot → copy Token → paste into .env
  4. OAuth2 → URL Generator → scopes: bot, applications.commands
     → permissions: Send Messages, Read Message History, Create Threads
  5. Open the generated URL in browser → invite bot to your server

Test all tokens:
  pytest tests/test_discord_tokens.py -v -s
```

## Pre-Deploy Checklist

See `agents/backend/production-readiness.md` for the full checklist.

## Guidelines

- Never commit `.env` — verify it's in `.gitignore` before proceeding
- No Kubernetes, Terraform, or cloud infrastructure needed
- Single docker-compose deployment is the intended production setup
