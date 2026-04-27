# NanoClaw — CLAUDE.md

## Project Overview

NanoClaw is a Discord bot that orchestrates a multi-agent AI system (CTO → PM → Dev → QA) to autonomously plan and implement software features. Users issue natural-language commands in Discord; the bot creates git worktrees, runs Claude Code CLI for implementation, and opens GitHub PRs.

Entry point: `nanoclaw/bot.py` — `main()` loads settings and starts the Discord client.

> **For detailed context**, see `.claude/context/` and the agent/workflow files referenced below.

---

## Architecture

```
nanoclaw/
  bot.py            # Discord client, event wiring, BotRegistry
  orchestrator.py   # Command parsing and routing
  agents/           # CTO, PM, Dev, QA agents (all subclass BaseAgent)
  workflow/         # WorkflowEngine, ApprovalGate, JobQueue
  tools/            # ClaudeCodeTool, GitTool, LLMRouter, BotRegistry
  memory/           # SharedMemory (SQLite), TaskStore (JSON), CostTracker
  safety/           # Auth, RateLimiter, BudgetGuard, DailyScheduler
  config/           # Settings (Pydantic), LLM routing config, prompts/
  tests/            # pytest + pytest-asyncio, all mocked
docs/
  specs/            # Approved design specs (before implementation)
  superpowers/plans/ # Implementation plans
  research/         # CTO-generated research documents
.claude/            # Claude Code configuration — see index below
```

### Key Data Flows

| Command | Flow |
|---|---|
| Natural language → @CTO | CTOAgent classifies → execute/respond/clarify/document |
| `execute` action | Orchestrator → WorkflowEngine → PM → Dev → QA → PR |
| `respond` / `clarify` | CTOAgent answers inline via CTO Discord client |
| `document` action | CTOAgent.research() (Sonnet) → markdown → optional git commit |
| `Dev implement <task_id>` | DevAgent worktree → ClaudeCodeTool → QA → push → PR |

All LLM calls go through `LLMRouter` (task-type routing with fallback chain).
Cost tracked per call in `memory/costs.db`.

---

## Discord Bot Identities

| Bot | Env Var | Role |
|---|---|---|
| CTO | `DISCORD_CTO_TOKEN` | Listener + analysis responses |
| PMO | `DISCORD_PMO_TOKEN` | Planning output |
| SED | `DISCORD_SED_TOKEN` | Dev/implementation updates |
| QAD | `DISCORD_QAD_TOKEN` | QA + code review results |
| NanoClaw (legacy) | `DISCORD_BOT_TOKEN` | Fallback if CTO token missing |

---

## Configuration

### `nanoclaw/config/settings.json` (local) / `settings.docker.json` (Docker)

Must be edited before first run:
- `discord.allowed_user_ids` — Discord user IDs allowed to issue commands
- `discord.command_channel_id`, `log_channel_id`, `commits_channel_id` — channel IDs
- `discord.bot_tokens` — maps role names to env var names
- `paths.project_path` — path to the repo the bot will code in
- `paths.worktree_base` — where temporary git worktrees are created
- `paths.github_repo` — `owner/repo` for PR creation
- `llm.routing` — maps task_type keys to provider + model

### Environment Variables (`.env`)

```
DISCORD_BOT_TOKEN=
DISCORD_CTO_TOKEN=
DISCORD_PMO_TOKEN=
DISCORD_SED_TOKEN=
DISCORD_QAD_TOKEN=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
GITHUB_TOKEN=
```

Override settings path: `NANOCLAW_SETTINGS=/path/to/settings.json`

---

## Running Locally

```bash
cd nanoclaw
pip install -r requirements.txt
cp .env.example .env   # fill in values
# Edit config/settings.json with your paths and channel IDs
python bot.py
```

## Running with Docker

```bash
cd nanoclaw
cp .env.example .env   # fill in values
# Edit config/settings.docker.json — use container-internal paths
docker compose up -d
```

Volumes required: project repo at `/workspace/project`, worktrees at `/workspace/worktrees`, `nanoclaw/memory/` for SQLite persistence.

## Running Tests

```bash
cd nanoclaw
python -m pytest tests/ -v
```

No live API calls — all LLM providers and Discord are mocked in `tests/conftest.py`.

---

## Key Design Constraints

- **Never push to `main`/`master`** — `GitTool.push()` raises if attempted
- **All feature work in git worktrees** — `project_path` must be a git repo
- **All LLM calls via LLMRouter** — never call provider SDKs directly from agents
- **New routing keys go in 3 places** — `settings.json`, `settings.docker.json`, `tests/conftest.py:SAMPLE_SETTINGS`
- **ClaudeCodeTool runs `claude` CLI** — must be on `PATH`
- **`gh` CLI must be authenticated** — used for PR creation
- **SQLite files are relative to CWD** — run `bot.py` from inside `nanoclaw/`
- **Rate limits and budget guards** — enforced before every LLM call; `BudgetExceededError` propagates to `bot.py`

---

## Adding a New Agent

1. Subclass `agents/base.py:BaseAgent`; see `.claude/agents/backend/python-architect.md`
2. Define a `frozen=True` `{Name}Decision` dataclass
3. Add prompt in `config/prompts/{name}_prompt.md`
4. Add routing key(s) in `config/settings.json`, `config/settings.docker.json`, `tests/conftest.py:SAMPLE_SETTINGS`
5. Wire into `NanoClawBot.__init__` in `bot.py`
6. Add routing in `orchestrator.py`
7. Write tests in `tests/test_{name}_agent.py`

## Adding a New Tool

1. Implement the tool class in `tools/{name}_tool.py`
2. Inject into the relevant agent constructor in `bot.py`
3. Write tests in `tests/test_{name}_tool.py`

---

## .claude/ Context Index

### Context (load in every session)
- `.claude/context/project-overview.md` — what NanoClaw is, architecture, data flows, setup
- `.claude/context/tech-stack.md` — Python 3.11, discord.py, Pydantic, pytest, Docker — full version table

### Agents — Backend
- `.claude/agents/backend/python-architect.md` — BaseAgent pattern, DI, settings, interface boundaries
- `.claude/agents/backend/concurrency.md` — asyncio patterns, gather, create_task, locks
- `.claude/agents/backend/fault-tolerance.md` — retry, LLM fallback, timeouts, graceful degradation
- `.claude/agents/backend/observability.md` — stdlib logging, cost tracking, session correlation
- `.claude/agents/backend/production-readiness.md` — Docker, env config, graceful shutdown, pre-deploy checklist

### Agents — Infrastructure
- `.claude/agents/infrastructure/cicd.md` — GitHub Actions CI for Python/pytest/Docker
- `.claude/agents/infrastructure/security.md` — Discord allowlist, API key hygiene, Docker hardening

### Agents — Testing
- `.claude/agents/testing/testing-strategy.md` — test pyramid, what to test, mock patterns, coverage targets
- `.claude/agents/testing/tooling.md` — pytest, pytest-asyncio, AsyncMock, ruff, coverage config
- `.claude/agents/testing/test-environment.md` — conftest.py fixtures, SAMPLE_SETTINGS, git repo fixture
- `.claude/agents/testing/ci-testing.md` — GitHub Actions test job, caching, coverage gate

### Agents — Product (unchanged)
- `.claude/agents/product/product-manager.md` — PRD writing
- `.claude/agents/product/product-research.md` — user/market research
- `.claude/agents/product/tech-lead-architect.md` — TRD/architecture docs

### Commands (slash commands)
- `/analyze-codebase` — analyze NanoClaw structure, agents, routing, test coverage
- `/design-architecture` — produce TRD for a NanoClaw feature
- `/generate-prd` — generate PRD for a new NanoClaw capability
- `/plan-feature` — create implementation plan from spec
- `/review-code` — comprehensive code review
- `/run-tests` — run pytest suite, analyze failures
- `/setup-infra` — Docker deployment, GitHub Actions CI, `.env` setup, bot token config

### Workflows
- `.claude/workflows/idea-to-production.md` — full feature lifecycle: brainstorm → spec → plan → TDD → PR → deploy
- `.claude/workflows/feature-development.md` — day-to-day implementation cycle
- `.claude/workflows/bug-triage-fix.md` — bug severity, investigation, TDD fix, verification
- `.claude/workflows/deployment-pipeline.md` — CI → docker compose → verify

### Templates
- `.claude/templates/architecture-decision-record.md` — ADR format
- `.claude/templates/prd-template.md` — PRD structure
- `.claude/templates/test-plan-template.md` — test plan structure
- `.claude/templates/trd-template.md` — Technical Requirements Document

### Not Applicable (stubbed)
- `.claude/agents/frontend/` — NanoClaw has no frontend
- `.claude/agents/infrastructure/kubernetes-architect.md` — no Kubernetes
- `.claude/agents/infrastructure/gitops.md` — no GitOps tooling
- `.claude/agents/infrastructure/terraform-architect.md` — no Terraform
- `.claude/agents/infrastructure/networking.md` — no VPC/K8s networking
- `.claude/agents/infrastructure/observability-infra.md` — no Prometheus/Grafana stack
- `.claude/agents/backend/go-architect.md` — replaced by python-architect
- `.claude/agents/testing/performance-chaos.md` — low-traffic bot, not applicable
