# NanoClaw — CLAUDE.md

## Project Overview

NanoClaw is a Discord bot that orchestrates a multi-agent AI system (PM → Dev → QA) to autonomously plan and implement software features. Users issue commands in Discord; the bot creates git worktrees, runs Claude Code CLI for implementation, and opens GitHub PRs.

Entry point: `nanoclaw/bot.py` — `main()` loads settings and starts the Discord client.

## Architecture

```
nanoclaw/
  bot.py            # Discord client, event wiring
  orchestrator.py   # Command parsing and routing
  agents/           # PM, Dev, QA agents (all inherit BaseAgent)
  workflow/         # WorkflowEngine, ApprovalGate, JobQueue
  tools/            # ClaudeCodeTool, GitTool, LLMRouter, ToolRegistry
  memory/           # SharedMemory (SQLite), TaskStore (JSON), CostTracker
  safety/           # Auth, RateLimiter, BudgetGuard, DailyScheduler
  config/           # Settings (Pydantic), LLM routing config, prompts
```

### Key Data Flows
- `PM define <instruction>` → PMAgent creates tasks in `memory/tasks.json`
- `Dev implement <task_id>` → DevAgent creates worktree, runs ClaudeCodeTool, runs QAAgent, pushes branch, opens PR
- All LLM calls go through `LLMRouter` which uses task-type-based routing with fallback chain
- Cost is tracked per call in `memory/costs.db`

## Commands (Discord)

| Command | Description |
|---|---|
| `@NanoClaw PM define <instruction>` | Create spec + tasks via PM agent |
| `@NanoClaw Dev implement <task_id>` | Run Dev→QA loop for a task |
| `@NanoClaw feature <instruction>` | Shorthand for PM define |
| `@NanoClaw status` | Queue depth, task counts, today's spend |
| `@NanoClaw cost` | Today's LLM cost breakdown |
| `@NanoClaw STOP` | Halt job queue |
| `@NanoClaw RESUME` | Resume job queue |

Approve/reject pending PRs via ✅/❌ emoji reactions on the bot's approval message.

## Configuration

### `nanoclaw/config/settings.json`
Must be edited before first run:
- `discord.allowed_user_ids` — Discord user IDs allowed to issue commands
- `discord.command_channel_id`, `log_channel_id`, `commits_channel_id` — channel IDs
- `paths.project_path` — absolute path to the repo the bot will code in
- `paths.worktree_base` — where temporary git worktrees are created
- `paths.github_repo` — `owner/repo` for PR creation

### Environment Variables (`.env`)
```
DISCORD_BOT_TOKEN=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
GITHUB_TOKEN=
```

Override settings path: `NANOCLAW_SETTINGS=/path/to/settings.json`

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
# Edit config/settings.docker.json — use container-internal paths:
#   project_path:  /workspace/project
#   worktree_base: /workspace/worktrees
docker compose up -d
```

See `nanoclaw/Dockerfile` and `nanoclaw/docker-compose.yml` for details.

**Volumes required:**
- The target project repo mounted at `/workspace/project`
- A writable directory for worktrees at `/workspace/worktrees`
- `nanoclaw/memory/` mounted for SQLite persistence

## Running Tests

```bash
cd nanoclaw
python -m pytest tests/ -v
```

Tests use `pytest-asyncio`. No live API calls — all LLM providers are mocked in `tests/conftest.py`.

## Key Design Constraints

- **Never push to `main`/`master`** — `GitTool.push()` raises if attempted
- **All work happens in git worktrees** — `project_path` must be a git repo
- **ClaudeCodeTool runs `claude` CLI** — the `claude` binary must be on `PATH`
- **`gh` CLI must be authenticated** — used for PR creation
- **SQLite files are relative to CWD** — run `bot.py` from inside `nanoclaw/`
- **Rate limits and budget guards** are enforced before every LLM call

## Adding a New Agent

1. Subclass `agents/base.py:BaseAgent`
2. Add a prompt in `config/prompts/`
3. Wire into `NanoClawBot.__init__` in `bot.py`
4. Add routing in `orchestrator.py`

## Adding a New Tool

1. Subclass `tools/base.py:Tool`
2. Register in `tools/tool_registry.py`
3. Inject into the relevant agent in `bot.py`
