# NanoClaw — Revised System Design
**Date:** 2026-03-30
**Status:** Awaiting Review
**Supersedes:** `2026-03-26-implementation-guide.md` (partial — see §8 for delta)

---

## Table of Contents

1. [Design Decisions](#1-design-decisions)
2. [Overall Architecture](#2-overall-architecture)
3. [Data Models](#3-data-models)
4. [PR Breakdown (7 Stacked PRs)](#4-pr-breakdown)
5. [Key Component Designs](#5-key-component-designs)
6. [Security Model](#6-security-model)
7. [Folder Structure](#7-folder-structure)
8. [Delta from Original Guide](#8-delta-from-original-guide)

---

## 1. Design Decisions

Agreed during brainstorming session (2026-03-29/30):

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Autonomy model | **Supervised (B)** — Discord approval gate before push | Safe while remote; one tap to approve |
| Retry limit | **2 retries (B)** — then escalate to Discord | Covers most transient issues without spinning |
| Progress UX | **Live thread (B)** — Discord thread per task | Visible from phone, interruptible |
| Code isolation | **Git worktrees (A)** | Lightweight, fast, native git, no disk bloat |
| LLM providers | **All three (C)** — Anthropic + OpenAI + Google | Cost optimisation + resilience from day one |
| Build approach | **Horizontal layers (1)** — bottom-up, 7 stacked PRs | Clean dependency order, each PR independently testable |

Additional decisions from principal-level review:

| Issue | Decision |
|-------|----------|
| Passive orchestrator | Add **WorkflowEngine** as first-class component |
| Auto-commit risk | 3-stage pipeline: **Draft → Verify → Approve → Push** |
| Flat task list | Tasks have `dependencies[]` and `retry_count` |
| Claude Code trusted blindly | **Verification Layer** wraps all Claude Code output |
| Sync Discord execution | **Async job queue** (asyncio) — background execution |
| No cost visibility | **Cost Tracker** on every LLM call, daily budget cap |
| Open Discord access | `allowed_user_ids` whitelist in config |

---

## 2. Overall Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  You (Discord on phone)                                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ @NanoClaw [command]
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Bot Layer  (bot.py)                                         │
│  • Listens for mentions in allowed channels                  │
│  • Creates Discord thread per task                           │
│  • Posts progress updates into thread                        │
│  • Handles ✅/❌ reactions for approval gate                 │
│  • Enforces allowed_user_ids whitelist                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator  (orchestrator.py)                             │
│  • Parses command → identifies target + instruction          │
│  • Enqueues jobs into Async Job Queue                        │
│  • Routes: workflow commands → WorkflowEngine                │
│            direct commands  → individual agent               │
│            system commands  → status / stop / resume        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Async Job Queue  (workflow/job_queue.py)                    │
│  • asyncio queue — prevents Discord timeout                  │
│  • One worker per job, max N concurrent                      │
│  • Posts "working…" immediately, updates thread on progress  │
│  • Respects STOP signal                                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  WorkflowEngine  (workflow/engine.py)                        │
│                                                              │
│   PM Agent ──► creates spec + tasks with dependencies        │
│       │                                                      │
│       ▼                                                      │
│   [for each task in dependency order]                        │
│       │                                                      │
│       ▼                                                      │
│   Dev Agent ──► runs Claude Code in git worktree             │
│       │             │                                        │
│       │             ▼                                        │
│       │        Verification Layer                            │
│       │        • files exist?                                │
│       │        • syntax clean? (go vet / tsc)                │
│       │        • tests pass?                                  │
│       │             │                                        │
│       ▼             ▼ (pass)                                 │
│   QA Agent ──► runs tests, validates acceptance criteria     │
│       │                                                      │
│       ├── PASS ──► Approval Gate (Discord ✅/❌)             │
│       │               │                                      │
│       │               ▼ (✅)                                 │
│       │           git push + PR created                      │
│       │                                                      │
│       └── FAIL ──► retry_count < 2?                         │
│                       ├── YES → back to Dev Agent            │
│                       └── NO  → escalate to Discord          │
└──────────────────────────┬──────────────────────────────────┘
                           │ (shared by all agents)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Shared Infrastructure                                       │
│                                                              │
│  Memory Layer          LLM Router           Tool Registry    │
│  ├─ SharedMemory       ├─ Anthropic          ├─ ClaudeCode   │
│  ├─ TaskStore          ├─ OpenAI             ├─ GitTool       │
│  ├─ CostTracker        ├─ Google             └─ (extensible) │
│  └─ ContextLoader      └─ fallback chain                     │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibility Map

| Component | Single Responsibility |
|-----------|----------------------|
| `Bot Layer` | Discord I/O — receive commands, post updates, handle reactions |
| `Orchestrator` | Parse + route commands, enqueue jobs |
| `AsyncJobQueue` | Background execution, progress reporting, stop signal |
| `WorkflowEngine` | PM→Dev→QA loop, retry logic, approval gate trigger |
| `VerificationLayer` | Assert Claude Code output is valid before QA sees it |
| `ApprovalGate` | Pause workflow, prompt Discord, await reaction, resume or cancel |
| `PMAgent` | Turn instructions into structured specs + dependency-ordered tasks |
| `DevAgent` | Implement tasks via Claude Code in isolated worktree |
| `QAAgent` | Validate implementation against acceptance criteria |
| `SharedMemory` | Persist + retrieve conversation history (SQLite) |
| `TaskStore` | CRUD for task JSON, dependency resolution |
| `CostTracker` | Log + roll up LLM cost per call / task / day |
| `ContextLoader` | Load Markdown context files into agent prompts |
| `LLMRouter` | Route to optimal model, fallback on failure, record cost |
| `ToolRegistry` | Register + invoke tools by name — extensible interface |
| `ClaudeCodeTool` | Subprocess wrapper for `claude -p ...`, with verification |
| `GitTool` | Worktree lifecycle, branch, commit, push, PR creation |

---

## 3. Data Models

### 3.1 Task Schema (`memory/tasks.json`)

```json
{
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Add /health endpoint",
      "description": "Create GET /health returning 200 + uptime JSON",
      "status": "open",
      "priority": "high",
      "created_by": "pm",
      "assigned_to": "dev",
      "dependencies": [],
      "retry_count": 0,
      "max_retries": 2,
      "acceptance_criteria": [
        "Returns HTTP 200 with JSON body",
        "Includes uptime in response",
        "Has unit test coverage"
      ],
      "worktree_path": null,
      "branch": null,
      "verification": {
        "files_created": [],
        "tests_passed": null,
        "syntax_clean": null,
        "last_verified_at": null
      },
      "pr_url": null,
      "discord_thread_id": null,
      "created_at": "2026-03-30T10:00:00Z",
      "updated_at": "2026-03-30T10:00:00Z"
    }
  ]
}
```

**Field notes:**
- `dependencies`: list of task IDs that must be `done` before this task starts
- `retry_count`: incremented each time a Dev attempt fails, whether from verification failure or QA failure — only incremented when a subsequent attempt will follow (not on the terminal failure)
- `worktree_path`: absolute path to git worktree for this task (set by DevAgent)
- `branch`: git branch name for this task (`nanoclaw/TASK-001-description`)
- `verification`: populated by VerificationLayer after each Claude Code execution
- `discord_thread_id`: the Discord thread posting progress for this task

**Task status state machine:**
```
open → in_progress → awaiting_qa → awaiting_approval → done
                  ↘ failed (retry_count >= max_retries)
```

---

### 3.2 Conversation Store (`memory/conversations.db`)

```sql
CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    role        TEXT NOT NULL,       -- 'user','pm','dev','qa','system'
    agent       TEXT,                -- which agent produced this
    content     TEXT NOT NULL,
    task_id     TEXT,                -- FK to tasks.json id
    model       TEXT,                -- model used for this call
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_usd    REAL DEFAULT 0.0,
    metadata    TEXT                 -- JSON blob for extra info
);

CREATE INDEX idx_conversations_task_id   ON conversations(task_id);
CREATE INDEX idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX idx_conversations_role      ON conversations(role);
```

---

### 3.3 Cost Log (`memory/costs.db`)

Separate table for fast rollup queries without scanning conversation history.

```sql
CREATE TABLE cost_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    session_id  TEXT NOT NULL,       -- groups all calls in one workflow run
    task_id     TEXT,
    agent       TEXT NOT NULL,       -- 'pm','dev','qa','router'
    provider    TEXT NOT NULL,       -- 'anthropic','openai','google'
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    cost_usd    REAL NOT NULL
);

CREATE INDEX idx_cost_session   ON cost_log(session_id);
CREATE INDEX idx_cost_task      ON cost_log(task_id);
CREATE INDEX idx_cost_timestamp ON cost_log(timestamp);
```

**Model pricing table** (used by CostTracker, kept in `config/pricing.json`):
```json
{
  "anthropic": {
    "claude-sonnet-4-6":          {"in": 3.00,  "out": 15.00},
    "claude-haiku-4-5-20251001":  {"in": 0.80,  "out": 4.00},
    "claude-opus-4-6":            {"in": 15.00, "out": 75.00}
  },
  "openai": {
    "gpt-4o":                     {"in": 2.50,  "out": 10.00},
    "gpt-4o-mini":                {"in": 0.15,  "out": 0.60}
  },
  "google": {
    "gemini-2.0-flash":           {"in": 0.10,  "out": 0.40},
    "gemini-2.0-pro":             {"in": 1.25,  "out": 5.00}
  }
}
```
*(prices per million tokens — update as providers change)*

---

### 3.4 Configuration (`config/settings.json`)

```json
{
  "discord": {
    "allowed_user_ids": ["YOUR_DISCORD_USER_ID"],
    "command_channel_id": "CHANNEL_ID",
    "log_channel_id": "CHANNEL_ID",
    "commits_channel_id": "CHANNEL_ID"
  },
  "workflow": {
    "max_retries": 2,
    "approval_timeout_minutes": 60,
    "job_timeout_minutes": 10,
    "max_concurrent_jobs": 2
  },
  "rate_limits": {
    "llm_calls_per_hour": 30,
    "claude_code_per_hour": 10,
    "git_pushes_per_hour": 5,
    "cooldown_minutes": 10
  },
  "budget": {
    "daily_limit_usd": 5.00,
    "warn_at_percent": 0.80,
    "daily_report_time": "09:00"
  },
  "llm": {
    "routing": {
      "coding":    {"provider": "anthropic", "model": "claude-sonnet-4-6"},
      "review":    {"provider": "anthropic", "model": "claude-sonnet-4-6"},
      "spec":      {"provider": "openai",    "model": "gpt-4o"},
      "simple":    {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
      "test":      {"provider": "anthropic", "model": "claude-sonnet-4-6"},
      "summarise": {"provider": "google",    "model": "gemini-2.0-flash"}
    },
    "fallback_chain": [
      ["anthropic", "claude-sonnet-4-6"],
      ["openai",    "gpt-4o"],
      ["google",    "gemini-2.0-pro"],
      ["anthropic", "claude-haiku-4-5-20251001"]
    ]
  },
  "paths": {
    "project_path": "/Users/yourusername/projects/yourproject",
    "worktree_base": "/Users/yourusername/projects/worktrees",
    "github_repo":   "yourname/yourproject"
  }
}
```

---

### 3.5 Context Files (`memory/context/`)

Markdown files loaded verbatim into every agent prompt.

| File | Written by | Purpose |
|------|-----------|---------|
| `project_overview.md` | You (manual) | What the project is, stack, current status |
| `architecture.md` | You + agents | Technical decisions, patterns, constraints |
| `conventions.md` | You (manual) | Coding standards, commit format, naming |
| `agent_notes.md` | Agents (append-only) | Cross-agent observations, discovered issues |

---

## 4. PR Breakdown

7 stacked PRs, each merging into the previous. Each PR is independently testable.

```
main
 └── nanoclaw/01-foundation
      └── nanoclaw/02-memory
           └── nanoclaw/03-llm-router
                └── nanoclaw/04-tools
                     └── nanoclaw/05-agents
                          └── nanoclaw/06-orchestrator
                               └── nanoclaw/07-safety
```

---

### PR1 — Foundation (`nanoclaw/01-foundation`)

**Goal:** Working project skeleton. Nothing runs yet, but everything is in the right place.

**Files created:**
```
nanoclaw/
├── bot.py                   # stub — "online" log only
├── orchestrator.py          # stub — echo command back
├── requirements.txt         # all dependencies pinned
├── .env.example             # template — never committed with real values
├── .gitignore               # .env, __pycache__, logs/, *.db
├── README.md                # setup instructions
├── config/
│   ├── settings.py          # Pydantic model — validates settings.json on load
│   ├── settings.json        # template with placeholder values
│   └── pricing.json         # LLM cost table
├── agents/    __init__.py
├── tools/     __init__.py
├── workflow/  __init__.py
├── memory/    __init__.py
└── logs/      .gitkeep
```

**Skeleton — `config/settings.py`:**
```python
from pydantic import BaseModel, Field
from pathlib import Path
import json

class DiscordConfig(BaseModel):
    allowed_user_ids: list[str]
    command_channel_id: str
    log_channel_id: str
    commits_channel_id: str

class WorkflowConfig(BaseModel):
    max_retries: int = 2
    approval_timeout_minutes: int = 60
    job_timeout_minutes: int = 10
    max_concurrent_jobs: int = 2

class Settings(BaseModel):
    discord: DiscordConfig
    workflow: WorkflowConfig
    # ... other sections

    @classmethod
    def load(cls, path: str = "config/settings.json") -> "Settings":
        with open(path) as f:
            return cls(**json.load(f))

settings = Settings.load()
```

**Acceptance criteria:**
- [ ] `pip install -r requirements.txt` completes without errors
- [ ] `python bot.py` starts without import errors
- [ ] `config/settings.py` raises `ValidationError` if required fields missing
- [ ] `.env` is in `.gitignore` and not tracked

---

### PR2 — Memory System (`nanoclaw/02-memory`)

**Goal:** All three storage layers working and testable in isolation.

**Files created:**
```
memory/
├── shared.py          # SharedMemory — conversation read/write
├── task_store.py      # TaskStore — task CRUD + dependency resolution
├── cost_tracker.py    # CostTracker — log + rollup cost
├── context_loader.py  # ContextLoader — read Markdown context files
├── schema.sql         # DDL for conversations.db + costs.db
├── tasks.json         # empty initial task list
└── context/
    ├── project_overview.md   # template
    ├── architecture.md       # template
    ├── conventions.md        # template
    └── agent_notes.md        # empty
```

**Skeleton — `memory/shared.py`:**
```python
import aiosqlite
from datetime import datetime, timezone

class SharedMemory:
    def __init__(self, db_path: str = "memory/conversations.db"):
        self.db_path = db_path

    async def save_message(self, role: str, agent: str, content: str,
                           task_id: str = None, model: str = None,
                           tokens_in: int = 0, tokens_out: int = 0,
                           cost_usd: float = 0.0) -> None:
        """Insert a conversation row. session_id is derived from task_id."""
        ...

    async def get_recent(self, limit: int = 10,
                         task_id: str = None) -> list[dict]:
        """Return most recent messages, optionally filtered by task_id.
        Returns list of dicts with keys: role, agent, content, timestamp."""
        ...
```

**Skeleton — `memory/context_loader.py`:**
```python
from pathlib import Path

class ContextLoader:
    def __init__(self, context_dir: str = "memory/context"):
        self.dir = Path(context_dir)

    async def load_all(self) -> str:
        """Concatenate all .md context files into a single string.
        Returns empty string if context dir is empty."""
        ...

    async def load(self, filename: str) -> str:
        """Load a single context file by name."""
        ...
```

**Skeleton — `memory/task_store.py`:**
```python
import asyncio
import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

class TaskStore:
    def __init__(self, path: str = "memory/tasks.json"):
        self.path = Path(path)
        self._lock = asyncio.Lock()  # guards JSON reads/writes under concurrent jobs

    # Mutating methods are async so they can acquire self._lock.
    # Read-only methods (get, list, get_ready) may be sync if access is single-threaded,
    # but are marked async here for consistency with the locking pattern.

    async def create(self, title: str, description: str,
                     priority: str = "medium",
                     dependencies: list[str] = None) -> dict:
        """Create a new task. Returns the created task dict."""
        ...

    async def get(self, task_id: str) -> Optional[dict]:
        """Get task by ID. Returns None if not found."""
        ...

    async def update(self, task_id: str, **fields) -> dict:
        """Update task fields. Raises if task not found."""
        ...

    async def list(self, status: str = None) -> list[dict]:
        """List tasks, optionally filtered by status."""
        ...

    async def get_ready(self) -> list[dict]:
        """Return tasks whose dependencies are all done, ordered by priority."""
        ...

    async def increment_retry(self, task_id: str) -> int:
        """Increment retry_count under lock. Returns new count."""
        ...
```

**Skeleton — `memory/cost_tracker.py`:**
```python
import aiosqlite
from datetime import datetime, timezone

class CostTracker:
    def __init__(self, db_path: str = "memory/costs.db"):
        self.db_path = db_path

    async def log(self, session_id: str, task_id: str,
                  agent: str, provider: str, model: str,
                  tokens_in: int, tokens_out: int) -> float:
        """Log a call. Returns cost_usd calculated from pricing table."""
        ...

    async def daily_total(self, date: str = None) -> float:
        """Return total USD spent today (or given date)."""
        ...

    async def task_total(self, task_id: str) -> float:
        """Return total USD spent on a task."""
        ...

    async def session_summary(self, session_id: str) -> dict:
        """Return per-model breakdown for a session."""
        ...
```

**Acceptance criteria:**
- [ ] `TaskStore.create()` persists to JSON and returns the task
- [ ] `TaskStore.get_ready()` returns only tasks with all deps done
- [ ] `CostTracker.log()` correctly calculates cost from `pricing.json`
- [ ] `CostTracker.daily_total()` returns 0.0 on empty DB
- [ ] `SharedMemory.save_message()` + `get_recent()` round-trip correctly

---

### PR3 — LLM Router (`nanoclaw/03-llm-router`)

**Goal:** Multi-provider LLM routing with fallback chain and cost recording.

**Files created:**
```
tools/
├── llm_router.py          # LLMRouter — main routing + fallback logic
└── providers/
    ├── __init__.py
    ├── base.py            # LLMProvider abstract base
    ├── anthropic_provider.py
    ├── openai_provider.py
    └── google_provider.py
```

**Skeleton — `tools/providers/base.py`:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    cost_usd: float

class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, messages: list[dict],
                       model: str, **kwargs) -> LLMResponse:
        """Call this provider. Raises ProviderError on failure."""
        ...

    @abstractmethod
    def models(self) -> list[str]:
        """Return list of supported model names."""
        ...
```

**Skeleton — `tools/llm_router.py`:**
```python
from tools.providers.base import LLMProvider, LLMResponse
from memory.cost_tracker import CostTracker
from config.settings import settings

class LLMRouter:
    def __init__(self, cost_tracker: CostTracker):
        self.providers: dict[str, LLMProvider] = {}  # name → provider
        self.cost_tracker = cost_tracker
        self._register_providers()

    async def route(self, task_type: str, messages: list[dict],
                    session_id: str, task_id: str = None,
                    agent: str = "unknown") -> LLMResponse:
        """Route to best provider for task_type. Falls back on failure."""
        primary = settings.llm.routing[task_type]
        chain = self._build_chain(primary)

        for provider_name, model in chain:
            try:
                provider = self.providers[provider_name]
                response = await provider.complete(messages, model)
                await self.cost_tracker.log(
                    session_id, task_id, agent,
                    provider_name, model,
                    response.tokens_in, response.tokens_out
                )
                return response
            except Exception as e:
                # log and try next in chain
                continue

        raise RuntimeError("All providers in fallback chain failed")

    def _build_chain(self, primary: dict) -> list[tuple[str, str]]:
        """Build fallback chain starting with primary provider.

        Prepends the task-specific primary model, then appends entries from
        fallback_chain that aren't already in the list. This means the primary
        model is tried first, and any overlap with fallback_chain is skipped
        rather than tried twice — deduplication is intentional.
        """
        chain = [(primary["provider"], primary["model"])]
        for p, m in settings.llm.fallback_chain:
            if (p, m) not in chain:
                chain.append((p, m))
        return chain
```

**Acceptance criteria:**
- [ ] Router uses correct model for each `task_type` from `settings.json`
- [ ] On provider failure, falls back to next in chain without raising
- [ ] `LLMResponse` includes correct `tokens_in`, `tokens_out`, `cost_usd`
- [ ] All three providers return `LLMResponse` with consistent structure
- [ ] `CostTracker.log()` called after every successful completion

---

### PR4 — Tools (`nanoclaw/04-tools`)

**Goal:** ClaudeCodeTool with verification layer, GitTool with worktree lifecycle.

**Files created:**
```
tools/
├── base.py              # Tool abstract base class
├── tool_registry.py     # ToolRegistry — register + invoke by name
├── claude_code.py       # ClaudeCodeTool + VerificationLayer
└── git_tool.py          # GitTool — worktree, branch, commit, push, PR
```

**Skeleton — `tools/base.py`:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = None
    metadata: dict = None

class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, input: str, **kwargs) -> ToolResult:
        ...
```

**Skeleton — `tools/claude_code.py`:**
```python
import subprocess, json, asyncio
from tools.base import Tool, ToolResult

class VerificationLayer:
    async def verify(self, worktree_path: str,
                     task: dict) -> tuple[bool, str]:
        """
        Run post-Claude-Code checks. Returns (passed, details).
        Checks: created files exist, syntax clean, tests pass.
        """
        ...

class ClaudeCodeTool(Tool):
    name = "claude_code"
    description = "Execute Claude Code CLI in a git worktree"

    def __init__(self, verifier: VerificationLayer):
        self.verifier = verifier

    async def run(self, instruction: str,
                  worktree_path: str,
                  task: dict,
                  timeout: int = 300) -> ToolResult:
        """
        Run Claude Code, then verify output.
        Returns ToolResult with success=False if verification fails.
        """
        ...
```

**Skeleton — `tools/git_tool.py`:**
```python
import git
from tools.base import Tool, ToolResult

class GitTool(Tool):
    name = "git"
    description = "Git operations — worktrees, branches, commits, PRs"

    def __init__(self, repo_path: str, worktree_base: str):
        self.repo = git.Repo(repo_path)
        self.worktree_base = worktree_base

    def create_worktree(self, task_id: str) -> str:
        """Create a git worktree for task. Returns worktree path."""
        ...

    def remove_worktree(self, worktree_path: str) -> None:
        """Remove worktree after task completes or fails."""
        ...

    def commit(self, worktree_path: str, message: str) -> str:
        """Stage all + commit in worktree. Returns short SHA."""
        ...

    def push(self, branch: str) -> str:
        """Push branch to remote. Returns branch name."""
        ...

    def create_pr(self, title: str, body: str,
                  branch: str) -> str:
        """Create GitHub PR via gh CLI. Returns PR URL."""
        ...

    async def run(self, input: str, **kwargs) -> ToolResult:
        """Generic Tool interface — parses action from input."""
        ...
```

**Acceptance criteria:**
- [ ] `GitTool.create_worktree()` creates an isolated directory with a fresh branch
- [ ] `ClaudeCodeTool.run()` calls subprocess, parses output, calls `VerificationLayer`
- [ ] `VerificationLayer.verify()` fails fast if expected files are missing
- [ ] `GitTool.remove_worktree()` cleans up even if task failed
- [ ] `ToolRegistry` resolves tools by name string

---

### PR5 — Agents (`nanoclaw/05-agents`)

**Goal:** PM, Dev, QA agents with production-grade system prompts, fully wired to memory + LLM router + tools.

**Files created:**
```
agents/
├── base.py          # BaseAgent
├── pm.py            # PMAgent
├── dev.py           # DevAgent
├── qa.py            # QAAgent
config/prompts/
├── pm_prompt.md
├── dev_prompt.md
└── qa_prompt.md
```

**Skeleton — `agents/base.py`:**
```python
from tools.llm_router import LLMRouter
from memory.shared import SharedMemory
from memory.context_loader import ContextLoader
import uuid

class BaseAgent:
    name: str
    task_type: str
    system_prompt: str

    def __init__(self, router: LLMRouter, memory: SharedMemory,
                 context: ContextLoader):
        self.router = router
        self.memory = memory
        self.context = context

    async def handle(self, instruction: str,
                     task_id: str = None,
                     session_id: str = None) -> str:
        session_id = session_id or str(uuid.uuid4())
        history = await self.memory.get_recent(limit=10, task_id=task_id)
        ctx = await self.context.load_all()
        messages = self._build_messages(instruction, history, ctx)

        response = await self.router.route(
            task_type=self.task_type,
            messages=messages,
            session_id=session_id,
            task_id=task_id,
            agent=self.name,
        )

        await self.memory.save_message(
            role=self.name, agent=self.name,
            content=response.content, task_id=task_id,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )
        return response.content

    def _build_messages(self, instruction, history, ctx) -> list[dict]:
        ...
```

**Dataclass — `agents/dev.py` (DevResult):**
```python
from dataclasses import dataclass, field

@dataclass
class DevResult:
    """Returned by DevAgent.implement(). Shape used by WorkflowEngine + QAAgent."""
    verification_passed: bool
    worktree_path: str
    branch: str
    details: str                    # human-readable summary of what was done
    files_changed: list[str] = field(default_factory=list)
    error: str = None               # set if verification_passed=False
    # pr_url is NOT here — set by commit_and_push() after approval
```

**Skeleton — `agents/dev.py`:**
```python
from agents.base import BaseAgent
from agents.dev import DevResult
from tools.claude_code import ClaudeCodeTool
from tools.git_tool import GitTool
from memory.task_store import TaskStore

class DevAgent(BaseAgent):
    name = "dev"
    task_type = "coding"

    def __init__(self, router, memory, context,
                 claude_code: ClaudeCodeTool,
                 git: GitTool,
                 task_store: TaskStore):
        super().__init__(router, memory, context)
        self.claude_code = claude_code
        self.git = git
        self.task_store = task_store

    async def implement(self, task: dict,
                        session_id: str = None) -> DevResult:
        """
        Full implementation cycle for one task:
        1. Create worktree  (git_tool.create_worktree)
        2. Build Claude Code instruction from task spec
        3. Execute Claude Code in worktree  (claude_code.run)
        4. Run VerificationLayer
        5. Return DevResult (success/failure + worktree_path + branch)
        Does NOT commit or push — that happens in commit_and_push() after approval.
        """
        ...

    async def commit_and_push(self, task: dict,
                              dev_result: DevResult) -> str:
        """
        Called ONLY after WorkflowEngine receives ✅ approval.
        1. git_tool.commit(dev_result.worktree_path, message)
        2. git_tool.push(dev_result.branch)
        3. git_tool.create_pr(title, body, dev_result.branch)
        4. git_tool.remove_worktree(dev_result.worktree_path)
        Returns pr_url.
        """
        ...
```

**PM prompt (`config/prompts/pm_prompt.md`) key sections:**
```markdown
## Role
You are the Product Manager agent in NanoClaw...

## Output Format
ALWAYS return valid JSON (no Markdown, no prose before/after):
```json
{
  "feature": "Feature name",
  "tasks": [
    {
      "id": "TASK-001",
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "dependencies": [],
      "acceptance_criteria": ["...", "..."]
    }
  ]
}
```

## Rules
- Check existing tasks before creating new ones (avoid duplicates)
- Keep tasks small — implementable in one Claude Code session (~30 min)
- All acceptance criteria must be testable by QA automatically
- Include `dependencies: []` even when empty
- Return only JSON — no commentary outside the JSON block
```

**Additions to `WorkflowEngine` class in `workflow/engine.py`** (`_parse_tasks` and `_order_by_dependencies` are instance methods of `WorkflowEngine`, not standalone functions):
```python
    # --- inside class WorkflowEngine: ---

    def _parse_tasks(self, spec: str) -> list[dict]:
        """Parse PM JSON output into task dicts. Raises ValueError on bad JSON."""
        import json
        try:
            data = json.loads(spec)
        except json.JSONDecodeError as e:
            raise ValueError(f"PM returned non-JSON output: {e}") from e
        tasks = data.get("tasks", [])
        if not tasks:
            raise ValueError("PM returned no tasks")
        # Inject default max_retries so _run_task() can always read it
        for task in tasks:
            task.setdefault("max_retries", settings.workflow.max_retries)
        return tasks

    def _order_by_dependencies(self, tasks: list[dict]) -> list[dict]:
        """Topological sort — tasks with no unmet deps come first."""
        ...
```

**Skeleton — `agents/pm.py`:**
```python
from agents.base import BaseAgent
from memory.task_store import TaskStore

class PMAgent(BaseAgent):
    name = "pm"
    task_type = "spec"  # routes to openai/gpt-4o per settings.json

    def __init__(self, router, memory, context, task_store: TaskStore):
        super().__init__(router, memory, context)
        self.task_store = task_store

    # PMAgent does NOT persist tasks — it returns JSON to WorkflowEngine.
    # WorkflowEngine calls _parse_tasks() then creates tasks via TaskStore.
    # This keeps PMAgent stateless and testable in isolation.
```

**Skeleton — `agents/qa.py`:**
```python
from agents.base import BaseAgent
from agents.dev import DevResult

class QAAgent(BaseAgent):
    name = "qa"
    task_type = "review"  # routes to anthropic/claude-sonnet per settings.json

    async def handle(self, task: dict, dev_result: DevResult,
                     session_id: str = None) -> dict:
        """
        Override of BaseAgent.handle() with task-aware signature.
        Evaluates dev_result against task.acceptance_criteria.
        Returns:
          {
            "passed": bool,
            "criteria": [{"criterion": str, "passed": bool, "notes": str}],
            "feedback": str   # summary for Dev on retry
          }
        """
        ...
```

**Acceptance criteria:**
- [ ] `PMAgent.handle()` returns valid JSON parseable by `_parse_tasks()`
- [ ] `DevAgent.implement()` creates worktree, runs Claude Code, returns verification result
- [ ] `QAAgent.handle()` returns `{"passed": bool, "criteria": [...], "feedback": str}`
- [ ] All agents save to conversation history with cost tracking
- [ ] Prompts load from Markdown files, not hardcoded strings

---

### PR6 — Orchestrator + WorkflowEngine + Discord Bot (`nanoclaw/06-orchestrator`)

**Goal:** Full PM→Dev→QA loop running via Discord commands, with live thread updates and approval gate.

**Files created:**
```
bot.py                      # full Discord bot implementation
orchestrator.py             # full command routing
workflow/
├── engine.py               # WorkflowEngine — PM→Dev→QA loop
├── approval_gate.py        # Discord reaction gate
└── job_queue.py            # asyncio background job queue
```

**Skeleton — `workflow/engine.py`:**
```python
from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent
from memory.task_store import TaskStore
from workflow.approval_gate import ApprovalGate
import uuid

class WorkflowEngine:
    def __init__(self, pm: PMAgent, dev: DevAgent, qa: QAAgent,
                 task_store: TaskStore, approval_gate: ApprovalGate,
                 progress_callback=None):
        self.pm = pm
        self.dev = dev
        self.qa = qa
        self.task_store = task_store
        self.gate = approval_gate
        self._progress = progress_callback or (lambda msg: None)

    async def run_feature(self, instruction: str,
                          session_id: str = None) -> dict:
        """Full PM→Dev→QA workflow for a feature request."""
        session_id = session_id or str(uuid.uuid4())
        await self._progress("📋 PM Agent creating spec...")

        spec = await self.pm.handle(instruction, session_id=session_id)
        tasks = self._parse_tasks(spec)

        results = []
        for task in self._order_by_dependencies(tasks):
            result = await self._run_task(task, session_id)
            results.append(result)
            if not result["success"]:
                break   # stop on unrecoverable failure

        return {"session_id": session_id, "tasks": results}

    async def _run_task(self, task: dict,
                        session_id: str) -> dict:
        """Dev → QA → retry loop for one task.

        retry_count is incremented ONCE per failed attempt (at the bottom of the loop),
        regardless of whether failure came from verification or QA. This keeps a single
        increment point and makes the retry budget easy to reason about.
        """
        max_retries = task.get("max_retries", settings.workflow.max_retries)
        for attempt in range(max_retries + 1):
            await self._progress(
                f"💻 Dev working on {task['id']} "
                f"(attempt {attempt + 1}/{task['max_retries'] + 1})..."
            )
            dev_result = await self.dev.implement(task, session_id)

            if not dev_result.verification_passed:
                if attempt >= task.get("max_retries", settings.workflow.max_retries):
                    await self._progress(
                        f"⚠️ {task['id']} verification failed after "
                        f"{task.get('max_retries', settings.workflow.max_retries)} "
                        f"retries. Manual intervention needed."
                    )
                    return {"task_id": task["id"], "success": False,
                            "reason": "verification failed, max retries exceeded",
                            "details": dev_result.error}
                # increment only when a subsequent attempt will follow
                await self.task_store.increment_retry(task["id"])
                continue

            await self._progress(f"✅ QA validating {task['id']}...")
            qa_result = await self.qa.handle(
                task=task, dev_result=dev_result, session_id=session_id
            )

            if qa_result["passed"]:
                await self._progress(
                    f"🚀 {task['id']} ready — awaiting your approval"
                )
                approved = await self.gate.request(task, dev_result)
                if approved:
                    # commit + push ONLY after approval
                    pr_url = await self.dev.commit_and_push(task, dev_result)
                    return {"task_id": task["id"], "success": True,
                            "pr_url": pr_url}
                else:
                    return {"task_id": task["id"], "success": False,
                            "reason": "rejected by user"}

            # QA failed — only increment if a subsequent attempt will follow
            max_retries = task.get("max_retries", settings.workflow.max_retries)
            if attempt >= max_retries:
                await self._progress(
                    f"⚠️ {task['id']} failed after {max_retries} retries. "
                    f"Manual intervention needed."
                )
                return {"task_id": task["id"], "success": False,
                        "reason": "max retries exceeded",
                        "qa_result": qa_result}
            # increment only when a subsequent attempt will follow
            await self.task_store.increment_retry(task["id"])

        return {"task_id": task["id"], "success": False, "reason": "unknown"}
```

**Skeleton — `workflow/approval_gate.py`:**
```python
import asyncio
import discord
from agents.dev import DevResult

class ApprovalGate:
    def __init__(self, bot: discord.Client,
                 timeout_minutes: int = 60):
        self.bot = bot
        self.timeout = timeout_minutes * 60
        self._pending: dict[str, asyncio.Future] = {}

    async def request(self, task: dict, dev_result: DevResult) -> bool:
        """
        Post approval message to Discord thread.
        Waits for ✅ or ❌ reaction from allowed user.
        Returns True if approved, False if rejected or timed out.
        """
        thread_id = task.get("discord_thread_id")
        ...

    def resolve(self, task_id: str, approved: bool) -> None:
        """Called by bot's on_reaction_add — resolves the pending future."""
        if task_id in self._pending:
            self._pending[task_id].set_result(approved)
```

**Skeleton — `workflow/job_queue.py`:**
```python
import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass
class Job:
    id: str
    fn: Callable[[], Awaitable]
    discord_thread_id: str = None

class JobQueue:
    def __init__(self, max_concurrent: int = 2):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._stop = False
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def enqueue(self, job: Job) -> None:
        await self._queue.put(job)

    async def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        """Worker loop — call once at startup as asyncio.create_task(queue.run()).
        Uses create_task so each job runs concurrently up to max_concurrent,
        rather than awaiting sequentially.

        Note: task_done() is called inside _execute()'s finally block, so
        await queue.join() works correctly even though jobs are fire-and-forget here.
        """
        while not self._stop:
            job = await self._queue.get()
            asyncio.create_task(self._execute(job))

    async def _execute(self, job: Job) -> None:
        async with self._semaphore:
            try:
                await job.fn()
            except Exception as e:
                # log error, notify Discord thread
                pass
            finally:
                self._queue.task_done()
```

**Acceptance criteria:**
- [ ] `@NanoClaw PM define X` → spec created, tasks saved, posted to thread
- [ ] `@NanoClaw Dev implement TASK-001` → WorkflowEngine runs, progress in thread
- [ ] On QA pass: bot posts approval message with ✅/❌ reactions
- [ ] ✅ reaction → commit + push + PR URL posted to thread
- [ ] ❌ reaction → task marked cancelled, thread updated
- [ ] Long job does NOT block Discord (asyncio queue)
- [ ] `@NanoClaw STOP` halts job queue and acks in channel

---

### PR7 — Safety & Control (`nanoclaw/07-safety`)

**Goal:** Rate limiting, cost budget enforcement, emergency stop, user whitelist, daily cost report.

**Files created:**
```
safety/
├── __init__.py
├── rate_limiter.py      # per-operation rate limits with cooldown
├── budget_guard.py      # daily budget cap, warn at threshold
├── auth.py              # user whitelist check
└── scheduler.py         # daily report cron task
```

**Skeleton — `safety/rate_limiter.py`:**
```python
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

class RateLimiter:
    def __init__(self, limits: dict):
        # limits: {"llm_calls_per_hour": 30, ...}
        self.limits = limits
        self._windows: dict[str, deque] = defaultdict(deque)

    def check(self, operation: str) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Allowed = False if operation would exceed rate limit.
        """
        ...

    def record(self, operation: str) -> None:
        """Record that operation was used once, now."""
        ...
```

**Skeleton — `safety/auth.py`:**
```python
from config.settings import settings

class Auth:
    def __init__(self, allowed_user_ids: list[str]):
        self._allowed = set(allowed_user_ids)

    def is_allowed(self, user_id: str) -> bool:
        """Returns True if user_id is in the whitelist. Silent-ignore contract:
        callers should NOT send any response to disallowed users."""
        return user_id in self._allowed
```

**Skeleton — `safety/budget_guard.py`:**
```python
from memory.cost_tracker import CostTracker

class BudgetGuard:
    def __init__(self, cost_tracker: CostTracker,
                 daily_limit_usd: float,
                 warn_at_percent: float = 0.80):
        """warn_at_percent: fractional value (0.0–1.0), e.g. 0.80 for 80%.
        Matches the float stored in settings.budget.warn_at_percent."""
        self.tracker = cost_tracker
        self.limit = daily_limit_usd
        self.warn_threshold = daily_limit_usd * warn_at_percent

    async def check(self) -> tuple[bool, str]:
        """
        Returns (allowed, message).
        allowed=False if daily spend >= limit.
        Returns warning message if spend >= warn_threshold.
        """
        ...
```

**Skeleton — `safety/scheduler.py`:**
```python
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

class DailyScheduler:
    def __init__(self, report_time: str, callback):
        """report_time: "HH:MM" string from settings.budget.daily_report_time.
        Uses local system time (no timezone config needed for a single-machine bot)."""
        self.hour, self.minute = map(int, report_time.split(":"))
        self.callback = callback  # async callable — posts report to Discord

    async def run(self) -> None:
        """Run forever, posting report once per day at configured time."""
        while True:
            await self._sleep_until_next()
            await self.callback()

    async def _sleep_until_next(self) -> None:
        """Sleep until the next occurrence of the configured time."""
        ...
```

**Discord commands added in this PR:**

| Command | Behaviour |
|---------|-----------|
| `@NanoClaw STOP` | Halt job queue, post ack, reject new jobs |
| `@NanoClaw RESUME` | Resume job queue from paused state |
| `@NanoClaw status` | Post: active jobs, today's spend, rate limit state |
| `@NanoClaw cost` | Post: today's spend by model and agent |

**Daily report** (auto-posted at 09:00 local time to log channel):
```
📊 NanoClaw Daily Report
Tasks completed: 3 | Failed: 1
LLM cost today: $0.47 / $5.00 limit
  anthropic/claude-sonnet: $0.31 (65%)
  openai/gpt-4o:           $0.12 (26%)
  google/gemini-flash:     $0.04  (9%)
```

**Acceptance criteria:**
- [ ] Commands from non-whitelisted users receive no response (silent ignore)
- [ ] `@NanoClaw STOP` halts within current job boundary (no mid-execution kill)
- [ ] LLM calls blocked when `daily_limit_usd` reached
- [ ] Warning Discord message when spend crosses `warn_at_percent`
- [ ] Rate limit cooldown message posted when limit hit
- [ ] Daily report posted automatically at configured time

---

## 5. Key Component Designs

### 5.1 WorkflowEngine State Machine

```
                    ┌─────────────────┐
                    │   IDLE          │
                    └────────┬────────┘
                             │ run_feature()
                             ▼
                    ┌─────────────────┐
                    │   PM_RUNNING    │
                    └────────┬────────┘
                             │ spec + tasks created
                             ▼
                    ┌─────────────────┐
                    │   DEV_RUNNING   │◄──────────────────┐
                    └────────┬────────┘                   │
                             │ Claude Code + verification  │
                    ┌────────▼────────┐                   │
                    │   QA_RUNNING    │                   │
                    └────────┬────────┘                   │
                             │                            │
                   ┌─────────┴──────────┐                │
                   │ PASS               │ FAIL            │
                   ▼                    ▼                 │
         ┌─────────────────┐  retry_count < max? ────► YES┘
         │ AWAITING_APPROVAL│         │
         └────────┬────────┘         NO
                  │                   │
         ┌────────┴────────┐          ▼
         │ ✅ approved      │  ┌─────────────────┐
         │                 │  │   ESCALATED     │
         ▼                 │  └─────────────────┘
  ┌─────────────────┐      │
  │   PUSHING       │      │ ❌ rejected
  └────────┬────────┘      │
           │               │
           ▼               ▼
  ┌─────────────────────────────┐
  │         DONE                │
  └─────────────────────────────┘
```

### 5.2 LLM Router Fallback Flow

```
route(task_type="coding", ...)
    │
    ├─ primary: anthropic/claude-sonnet-4-6
    │     │ success → return LLMResponse
    │     │ failure (rate limit / timeout / 5xx)
    │           ▼
    ├─ fallback[1]: openai/gpt-4o
    │     │ success → return LLMResponse
    │     │ failure
    │           ▼
    ├─ fallback[2]: google/gemini-2.0-pro
    │     │ success → return LLMResponse
    │     │ failure
    │           ▼
    └─ fallback[3]: anthropic/claude-haiku-4-5-20251001
          │ success → return LLMResponse
          │ failure
                ▼
          raise RuntimeError("All providers failed")
          → post to Discord: "⚠️ All LLM providers unreachable"
```

### 5.3 Git Worktree Lifecycle

```
Task created
    │
    ▼
git_tool.create_worktree(task_id)
    → creates /worktrees/TASK-001/
    → creates branch nanoclaw/TASK-001-title
    │
    ▼
ClaudeCodeTool.run(instruction, worktree_path)
    → subprocess in /worktrees/TASK-001/
    │
    ▼
VerificationLayer.verify(worktree_path, task)
    │
    ├─ FAIL → log issue, return to Dev for retry
    │          (worktree kept for next attempt)
    │
    └─ PASS → QA Agent validates
                   │
                   ├─ FAIL → increment retry, back to Dev
                   │
                   └─ PASS → ApprovalGate.request()
                                  │
                                  ├─ ✅ → git_tool.commit(worktree_path)
                                  │       git_tool.push(branch)
                                  │       git_tool.create_pr(...)
                                  │       git_tool.remove_worktree()
                                  │
                                  └─ ❌ → git_tool.remove_worktree()
                                          task marked cancelled
```

---

## 6. Security Model

### 6.1 User Authorization
- All Bot Layer handlers check `str(message.author.id)` against `settings.discord.allowed_user_ids`
- Non-whitelisted users: **silent ignore** (no response, no error — avoids information disclosure)
- Authorization check happens BEFORE any command parsing or job enqueuing

### 6.2 Secrets Management
- `.env` contains all API keys — never committed (enforced by `.gitignore`)
- `settings.json` contains no secrets — safe to commit
- `.env.example` shows required key names with placeholder values

### 6.3 Git Safety
- `GitTool` never pushes to `main` directly — branch protection enforced in code
- PR creation requires human merge via GitHub
- `--force` push explicitly forbidden in `GitTool.push()`

### 6.4 Claude Code Scope
- Claude Code subprocess runs with `cwd=worktree_path` — cannot access files outside worktree
- No shell commands that touch files outside project root (enforced by `.claude/settings.json` deny rules)

---

## 7. Folder Structure

```
nanoclaw/
├── bot.py                         # Discord bot entry point
├── orchestrator.py                # Command routing
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── config/
│   ├── settings.py                # Pydantic config model
│   ├── settings.json              # Runtime config (no secrets)
│   ├── pricing.json               # LLM cost table
│   └── prompts/
│       ├── pm_prompt.md
│       ├── dev_prompt.md
│       └── qa_prompt.md
│
├── agents/
│   ├── __init__.py
│   ├── base.py
│   ├── pm.py
│   ├── dev.py
│   └── qa.py
│
├── tools/
│   ├── __init__.py
│   ├── base.py                    # Tool + ToolResult
│   ├── tool_registry.py
│   ├── llm_router.py
│   ├── claude_code.py             # + VerificationLayer
│   ├── git_tool.py
│   └── providers/
│       ├── __init__.py
│       ├── base.py                # LLMProvider ABC
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       └── google_provider.py
│
├── workflow/
│   ├── __init__.py
│   ├── engine.py                  # WorkflowEngine
│   ├── approval_gate.py
│   └── job_queue.py
│
├── memory/
│   ├── __init__.py
│   ├── shared.py                  # SharedMemory (conversations)
│   ├── task_store.py
│   ├── cost_tracker.py
│   ├── context_loader.py
│   ├── schema.sql
│   ├── tasks.json
│   └── context/
│       ├── project_overview.md
│       ├── architecture.md
│       ├── conventions.md
│       └── agent_notes.md
│
├── safety/
│   ├── __init__.py
│   ├── rate_limiter.py
│   ├── budget_guard.py
│   ├── auth.py
│   └── scheduler.py
│
├── tests/
│   ├── conftest.py                # shared fixtures (settings, mocks)
│   ├── test_config.py             # Settings.load() validation (PR1)
│   ├── test_memory.py             # TaskStore, SharedMemory, CostTracker
│   ├── test_llm_router.py         # routing, fallback, cost logging
│   ├── test_tools.py              # VerificationLayer, GitTool (mocked git)
│   ├── test_agents.py             # PM/Dev/QA agent logic
│   ├── test_workflow_engine.py    # full PM→Dev→QA loop (mocked agents)
│   └── test_safety.py             # RateLimiter, BudgetGuard, Auth
│
└── logs/
    └── .gitkeep
```

---

## 8. Delta from Original Guide

Changes from `2026-03-26-implementation-guide.md`:

| Section | Original | Revised |
|---------|----------|---------|
| §1 Architecture | Orchestrator = passive router | + WorkflowEngine state machine |
| §1 Architecture | No approval gate | 3-stage: Draft → Verify → Approve |
| §3 Agent Design | Dev auto-commits + pushes | Commit/push only after ✅ reaction |
| §3 Agent Design | No verification layer | VerificationLayer wraps Claude Code |
| §4 Memory System | Flat task list | Tasks have `dependencies[]`, `retry_count`, `worktree_path` |
| §4 Memory System | No cost tracking | `cost_log` table + `CostTracker` class |
| §5 Claude Code | Trusted executor | + VerificationLayer (files, syntax, tests) |
| §6 GitHub | Direct branch push | Git worktree isolation, push only on approval |
| §8 Multi-LLM | Router described | Full fallback chain implementation |
| §9 Implementation | 8 steps (flat) | 7 stacked PRs (layered, each testable) |
| §11 Safety | Phase 11 add-on | Safety as first-class layer (PR7) |
| NEW | — | `AsyncJobQueue` prevents Discord timeouts |
| NEW | — | `allowed_user_ids` whitelist |
| NEW | — | Daily cost report to Discord |

---

*Spec written by AI/Context Engineer — review and confirm before implementation begins.*
