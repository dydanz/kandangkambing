---
name: project-overview
description: NanoClaw project context — what it is, stack, architecture, entry points, and key data flows. Load this in every session.
type: reference
---

# NanoClaw — Project Overview

## What It Is

NanoClaw is a Discord bot that orchestrates a multi-agent AI system (PM → Dev → QA → CTO) to autonomously plan and implement software features. Users issue natural-language commands in Discord; the bot creates git worktrees, runs the `claude` CLI for implementation, and opens GitHub PRs.

**Users:** Developers who want AI-assisted feature development via Discord.

**Core value:** Type a feature request in Discord → get a PR opened with code, tests, and CI within minutes.

## Architecture

```
Discord (user mentions @CTO)
    ↓
bot.py — CTO Discord client (listener), event wiring, BotRegistry
    ↓
CTOAgent.process() — Haiku classifies intent → CTODecision
    ↓
┌─ action="execute"  → Orchestrator.handle()
│       ↓
│   WorkflowEngine → PMAgent → DevAgent → QAAgent
│       ↓              ↓           ↓          ↓
│   JobQueue      PM Discord   SED Discord  QAD Discord
│
├─ action="respond"  → CTO Discord client sends inline answer
├─ action="clarify"  → CTO Discord client asks question
└─ action="document" → CTO researches (Sonnet) → posts markdown → optional git commit
```

## Repository Structure

```
kandangkambing/
  nanoclaw/
    bot.py              # Entry point — Discord client, event wiring
    orchestrator.py     # Command parsing and routing
    agents/             # PM, Dev, QA, CTO agents (all subclass BaseAgent)
    workflow/           # WorkflowEngine, ApprovalGate, JobQueue
    tools/              # ClaudeCodeTool, GitTool, LLMRouter, BotRegistry
    memory/             # SharedMemory (SQLite), TaskStore (JSON), CostTracker
    safety/             # Auth, RateLimiter, BudgetGuard, DailyScheduler
    config/             # Settings (Pydantic), routing config, prompts/
    tests/              # pytest + pytest-asyncio, all mocked
  docs/
    specs/              # Design specs (approved before implementation)
    superpowers/plans/  # Implementation plans
    research/           # CTO-generated research docs
  .claude/              # Claude Code configuration
```

## Key Data Flows

| Command | Flow |
|---|---|
| `@CTO PM define <instruction>` | PMAgent creates spec + tasks in `memory/tasks.json` |
| `@CTO Dev implement <task_id>` | DevAgent creates worktree → ClaudeCodeTool → QAAgent → push → PR |
| `@CTO feature <instruction>` | Shorthand for PM define |
| `@CTO status` | Returns queue depth, task counts, today's spend |
| `@CTO research <topic>` | CTOAgent → research() via Sonnet → markdown doc |

## Discord Bot Identities

| Bot | Token Env Var | Role |
|---|---|---|
| CTO | `DISCORD_CTO_TOKEN` | Listener + analysis responses |
| PMO | `DISCORD_PMO_TOKEN` | Planning output |
| SED | `DISCORD_SED_TOKEN` | Dev/implementation updates |
| QAD | `DISCORD_QAD_TOKEN` | QA + code review results |
| NanoClaw (legacy) | `DISCORD_BOT_TOKEN` | Fallback |

## Development Setup

```bash
cd nanoclaw
pip install -r requirements.txt
cp .env.example .env   # fill in tokens and API keys
# Edit config/settings.json with your Discord channel IDs and project path
python bot.py
```

## Docker Setup

```bash
cd nanoclaw
cp .env.example .env
# Edit config/settings.docker.json (use /workspace/ paths)
docker compose up -d
```

## Running Tests

```bash
cd nanoclaw
python -m pytest tests/ -v
```

All tests are mocked — no live API keys needed.

## Key Constraints

- Never push to `main`/`master` — `GitTool.push()` raises if attempted
- All feature work happens in git worktrees (`worktree_base` directory)
- `claude` CLI must be on PATH (used by ClaudeCodeTool)
- `gh` CLI must be authenticated (used for PR creation)
- SQLite files are relative to CWD — run `bot.py` from inside `nanoclaw/`
- Rate limits and budget guards enforced before every LLM call

## Team

Solo project — Dandi Diputra (dandidiputra@gmail.com).
