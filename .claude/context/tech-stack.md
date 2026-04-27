---
name: tech-stack
description: NanoClaw technology choices, versions, and conventions for every layer of the stack.
type: reference
---

# NanoClaw Technology Stack

## Core Runtime

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Application language |
| discord.py | 2.x | Discord bot framework (async WebSocket) |
| asyncio | stdlib | Concurrency model |

## LLM Integration

| Technology | Version | Purpose |
|---|---|---|
| anthropic | latest | Anthropic SDK (Claude) |
| openai | latest | OpenAI SDK (fallback) |
| google-generativeai | latest | Google SDK (fallback) |

LLM calls go through `tools/llm_router.py` — task-type-based routing with fallback chain. Never call provider SDKs directly from agents.

**Routing keys** (defined in `config/settings.json` `llm.routing`):
| Key | Default model | Used for |
|---|---|---|
| `classify` | claude-haiku-4-5 | CTOAgent intent classification |
| `implement` | claude-sonnet-4-6 | DevAgent code generation |
| `research` | claude-sonnet-4-6 | CTOAgent deep research/docs |
| `qa` | claude-haiku-4-5 | QAAgent test analysis |

## Configuration

| Technology | Version | Purpose |
|---|---|---|
| Pydantic | v2 | Settings validation (`config/settings.py`) |
| python-dotenv | latest | `.env` loading |

Settings files: `config/settings.json` (local), `config/settings.docker.json` (Docker).

## Storage

| Technology | Version | Purpose |
|---|---|---|
| sqlite3 | stdlib | SharedMemory (messages, costs) |
| JSON files | — | TaskStore (`memory/tasks.json`) |

No ORM. `SharedMemory` uses raw `sqlite3`. `TaskStore` reads/writes JSON directly.

## Git & GitHub

| Technology | Version | Purpose |
|---|---|---|
| GitPython | 3.x | Git operations (worktrees, commits, push) |
| gh CLI | latest | PR creation (subprocess call) |
| claude CLI | latest | Code implementation (subprocess call) |

## Testing

| Technology | Version | Purpose |
|---|---|---|
| pytest | 8.x | Test runner |
| pytest-asyncio | 0.23+ | Async test support |
| pytest-cov | 5.x | Coverage reporting |
| unittest.mock | stdlib | AsyncMock, MagicMock, patch |

No Testcontainers, no real database in tests. SQLite runs in-memory or tmp dirs.

## Linting & Formatting

| Technology | Version | Purpose |
|---|---|---|
| ruff | latest | Linting + formatting (replaces flake8/black/isort) |

## Deployment

| Technology | Version | Purpose |
|---|---|---|
| Docker | 24+ | Container build |
| docker-compose | 2.x | Single-container deployment |

No Kubernetes, no Terraform, no cloud infrastructure.

## CI/CD

| Technology | Version | Purpose |
|---|---|---|
| GitHub Actions | — | CI pipeline (lint + test + build) |
| GHCR | — | Container registry |

## Python Conventions

- Module names: `snake_case.py`
- Class names: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- All agent methods: `async def` (asyncio event loop)
- Error handling: `logger.error("context: %s", e)` — include context, don't just log `e`
- Type hints: required for function signatures, optional for local variables

## Git Conventions

- Branch naming: `feature/[description]`, `fix/[description]`, `chore/[description]`
- Commit format: `type(scope): description` (conventional commits)
  - Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
- PR size: < 400 lines preferred — split larger changes
- Never commit `.env` or secrets
- Feature branches only — never push to `main`/`master` directly
