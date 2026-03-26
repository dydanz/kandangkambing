# kandangkambing

## Discord-Based Multi-Agent Coding System using NanoClaw

**Complete Implementation Guide**

Claude Code + GitHub + Mac Mini

Version 1.0 | March 2026

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Phase 1 — System Architecture](#phase-1--system-architecture)
- [Phase 2 — Technology Stack](#phase-2--technology-stack)
- [Phase 3 — Agent Design](#phase-3--agent-design)
- [Phase 4 — Memory System](#phase-4--memory-system)
- [Phase 5 — Claude Code Integration](#phase-5--claude-code-integration)
- [Phase 6 — GitHub Integration](#phase-6--github-integration)
- [Phase 7 — Discord UX Design](#phase-7--discord-ux-design)
- [Phase 8 — Multi-LLM Strategy](#phase-8--multi-llm-strategy)
- [Phase 9 — Step-by-Step Implementation](#phase-9--step-by-step-implementation)
- [Phase 10 — End-to-End Workflow Example](#phase-10--end-to-end-workflow-example)
- [Phase 11 — Safety & Control](#phase-11--safety--control)
- [Phase 12 — Future Extensions](#phase-12--future-extensions)
- [Appendix A — Complete Folder Structure](#appendix-a--complete-folder-structure)
- [Appendix B — Troubleshooting Guide](#appendix-b--troubleshooting-guide)

---

## Executive Summary

NanoClaw is a system that lets you command AI agents through Discord to build software automatically. Instead of sitting at your computer writing code, you send messages in Discord like "Dev, implement a login page" and AI agents on your Mac Mini write the code, test it, and push it to GitHub.

The system consists of five core layers:

- **Discord Interface:** Where you type commands and see results.
- **Orchestrator:** The brain that routes your commands to the right agent.
- **Agent System:** Three AI agents (Product Manager, Developer, QA), each with specialised roles.
- **Memory Layer:** A shared knowledge base so agents stay in sync.
- **Execution Layer:** Claude Code running on your Mac Mini, actually writing and testing code.

> **Key Benefit:** You can be anywhere in the world. As long as you have Discord, you can command your AI team to build software on your Mac Mini at home.

This document walks you through every step from zero to a working system. No prior experience with AI infrastructure is required.

---

## Phase 1 — System Architecture

### 1.1 High-Level Overview

Here is how every piece fits together. Think of it like a relay race — each layer hands off to the next:

```
You (on phone/laptop)
    │
    ▼
Discord (chat message)
    │
    ▼
NanoClaw Bot (Orchestrator)     ← Runs on Mac Mini
    │
    ├─── PM Agent
    ├─── Dev Agent
    └─── QA Agent
    │
    ▼
Memory Layer (SQLite + JSON)    ← Shared knowledge
    │
    ▼
Execution Layer
    ├─── Claude Code CLI          ← Writes/edits code
    └─── Git / GitHub             ← Version control
```

### 1.2 Component Breakdown

#### Discord Layer

This is your remote control. You type commands in a Discord channel. The NanoClaw bot listens for messages that start with a specific prefix (like `!nc` or `@NanoClaw`) and forwards them to the orchestrator.

> **Why Discord?** It works on every device, supports rich text and file uploads, has an excellent bot API, and you already use it. No need to build a custom UI.

#### Orchestrator

The orchestrator is a Python process running on your Mac Mini. It receives Discord messages, figures out which agent should handle the request, and manages the workflow. Think of it as a project manager for your AI team.

**Responsibilities:**

- Parse incoming commands to identify the target agent (PM, Dev, or QA)
- Maintain conversation state so agents can refer to earlier messages
- Coordinate multi-step workflows (e.g., PM defines, Dev builds, QA tests)
- Return results to Discord

#### Agent System

Each agent is a Python class with a specific system prompt, access to tools, and a defined role. They all share the same memory layer but have different capabilities:

| Agent | Role | Tools Available |
|-------|------|-----------------|
| PM (Product Manager) | Writes specs, breaks down features into tasks, prioritises work | Memory read/write, task management |
| Dev (Developer) | Writes code, modifies files, runs Claude Code, commits to Git | Claude Code CLI, Git, file system, memory |
| QA (Quality Assurance) | Writes tests, runs tests, validates code against specs | Test runner, Claude Code CLI, memory |

#### Memory Layer

All agents share a central memory system. This prevents the classic AI problem where one agent contradicts another. The memory has three tiers:

- **Conversation History:** A log of every message and response (stored in SQLite).
- **Task State:** What has been assigned, what is in progress, what is done (JSON file).
- **Project Context:** Summaries, architectural decisions, and conventions (Markdown files).

#### Execution Layer

This is where real work happens. When the Dev agent needs to write code, it calls Claude Code CLI on your Mac Mini. Claude Code can read your project files, write new code, and run terminal commands. After the code is written, Git commands push it to GitHub.

> **Important:** Everything runs locally on your Mac Mini. No cloud servers, no remote desktop. Discord is only a communication channel.

### 1.3 Data Flow Example

Let us trace a real command through the system:

1. **You type:** "@NanoClaw Dev, add a /health endpoint to the API"
2. Discord bot receives the message and extracts: target=Dev, instruction="add a /health endpoint to the API"
3. Orchestrator loads relevant memory (project context, recent tasks)
4. Dev agent constructs a prompt with the instruction plus context
5. Dev agent calls Claude Code CLI, which reads the codebase and writes the endpoint
6. Dev agent runs the code to verify it works
7. Dev agent commits the change and pushes to GitHub
8. Orchestrator sends the result back to Discord: "Added /health endpoint. Commit: abc123"

---

## Phase 2 — Technology Stack

### 2.1 Stack Overview

Every technology choice is made for simplicity. You do not need Kubernetes or Docker for the initial setup. We start with the simplest thing that works and add complexity only when needed.

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Largest AI ecosystem, excellent libraries, easy to learn |
| Discord Bot | discord.py | Most mature Python Discord library, async support |
| Agent Orchestration | Custom Python classes | Simple, no heavy framework overhead, full control |
| Memory (conversations) | SQLite | Zero setup, file-based, perfect for a single machine |
| Memory (tasks) | JSON files | Human-readable, easy to debug, Git-friendly |
| Memory (context) | Markdown files | Can be read by humans and AI equally well |
| LLM Access | anthropic, openai, google-generativeai | Official Python SDKs for each provider |
| Code Execution | Claude Code CLI | Already installed, runs locally, powerful |
| Version Control | GitPython | Python wrapper for Git operations |
| Process Management | launchd | Built into macOS, auto-restart on crash |

### 2.2 Python Dependencies

Here is the complete list of Python packages you will install:

```txt
# requirements.txt
discord.py>=2.3.0        # Discord bot framework
anthropic>=0.40.0        # Claude API client
openai>=1.50.0           # GPT API client
google-generativeai>=0.8 # Gemini API client
gitpython>=3.1.40        # Git operations
aiosqlite>=0.19.0        # Async SQLite for memory
python-dotenv>=1.0.0     # Environment variable management
pydantic>=2.5.0          # Data validation for configs
```

### 2.3 Prerequisites Checklist

Before you start building, make sure you have these ready:

| Item | How to Get It |
|------|--------------|
| Mac Mini (always on) | Already have it |
| Python 3.11+ | `brew install python@3.11` |
| Node.js (for Claude Code) | `brew install node` |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Git | `brew install git` (or Xcode tools) |
| Discord Account | discord.com |
| Discord Developer Application | discord.com/developers/applications |
| Anthropic API Key | console.anthropic.com |
| OpenAI API Key (optional) | platform.openai.com |
| Google AI API Key (optional) | aistudio.google.com |
| GitHub Account + SSH Key | github.com → Settings → SSH Keys |

> **Cost Estimate:** Claude API costs roughly $3–15 per million input tokens depending on model. For a personal project, expect $10–50/month. Discord bots are free. Mac Mini electricity is minimal.

---

## Phase 3 — Agent Design

### 3.1 Agent Architecture

Each agent follows the same structural pattern: a system prompt that defines its personality and rules, a set of tools it can use, and access to shared memory. The difference between agents is only in their prompts and tool access.

```python
class BaseAgent:
    def __init__(self, name, system_prompt, tools):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.memory = SharedMemory()  # Same instance for all agents

    async def handle(self, user_message, context):
        # 1. Load relevant memory
        history = await self.memory.get_relevant(user_message)
        # 2. Build prompt with context
        prompt = self.build_prompt(user_message, history, context)
        # 3. Call LLM
        response = await self.call_llm(prompt)
        # 4. Execute any tool calls
        result = await self.execute_tools(response)
        # 5. Save to memory
        await self.memory.save(user_message, result)
        return result
```

### 3.2 PM Agent (Product Manager)

The PM agent is your strategic thinker. It takes vague ideas and turns them into structured, actionable specifications that the Dev agent can implement.

#### System Prompt (Simplified)

```python
PM_SYSTEM_PROMPT = """
You are a Product Manager AI agent in the NanoClaw system.

Your responsibilities:
- Take user ideas and create clear feature specifications
- Break features into small, implementable tasks
- Prioritise tasks based on dependencies and value
- Write acceptance criteria for each task

Output format for specs:
  Feature: [name]
  Description: [what it does]
  Tasks:
    - Task 1: [description] | Priority: [high/medium/low]
    - Task 2: ...
  Acceptance Criteria:
    - [ ] Criterion 1
    - [ ] Criterion 2

Rules:
- Always check existing tasks before creating new ones
- Reference task IDs when relating tasks
- Keep tasks small enough to implement in one session
"""
```

#### PM Tools

- **create_task(title, description, priority):** Saves a new task to the task database
- **list_tasks(status):** Retrieves tasks filtered by status (open, in_progress, done)
- **update_task(task_id, updates):** Modifies an existing task
- **read_context():** Loads project context and architectural decisions

### 3.3 Dev Agent (Developer)

The Dev agent is your coder. It takes tasks (usually created by the PM) and implements them using Claude Code on your Mac Mini. It has the most powerful tool set because it can modify your actual codebase.

#### System Prompt (Simplified)

```python
DEV_SYSTEM_PROMPT = """
You are a Software Developer AI agent in the NanoClaw system.

Your responsibilities:
- Implement features based on task specs from PM
- Write clean, well-documented code
- Follow project conventions (check context.md)
- Commit changes with clear messages

Workflow:
1. Read the task specification
2. Check existing code for context
3. Implement the feature using Claude Code
4. Verify the implementation compiles/runs
5. Commit and push to GitHub
6. Update task status to 'done'

Rules:
- NEVER force-push to main
- Always create a feature branch
- Ask for confirmation before destructive operations
"""
```

#### Dev Tools

- **run_claude_code(instruction):** Executes Claude Code CLI with the given instruction on the local repo
- **git_commit(message):** Stages all changes and commits with a message
- **git_push(branch):** Pushes to the specified branch on GitHub
- **git_create_branch(name):** Creates and checks out a new branch
- **read_file(path):** Reads a file from the project
- **list_files(directory):** Lists files in a directory

### 3.4 QA Agent (Quality Assurance)

The QA agent validates that the code matches the specification. It writes tests, runs them, and reports issues. It acts as a safety net before code gets merged.

#### System Prompt (Simplified)

```python
QA_SYSTEM_PROMPT = """
You are a QA Engineer AI agent in the NanoClaw system.

Your responsibilities:
- Write test cases based on PM specifications
- Run tests and report results
- Validate code matches acceptance criteria
- Report bugs with clear reproduction steps

Workflow:
1. Read the task specification and acceptance criteria
2. Write appropriate tests (unit, integration)
3. Run tests using Claude Code
4. Compare results against acceptance criteria
5. Report pass/fail with details

Rules:
- Always reference the task ID being tested
- Be specific about failures
- Suggest fixes when possible
"""
```

### 3.5 Inter-Agent Communication

Agents do not talk to each other directly. Instead, they communicate through the shared memory layer. This keeps the system simple and prevents complex agent-to-agent messaging loops.

```
Communication Flow:

  PM writes spec → Saved to memory (tasks.json)
       │
  Dev reads spec from memory → Implements → Updates task status
       │
  QA reads spec + code from memory → Tests → Reports results
```

The orchestrator can also chain agents automatically. For example, when you say "build and test the login feature," the orchestrator will first call the Dev agent, wait for completion, then automatically call the QA agent.

---

## Phase 4 — Memory System

### 4.1 Why Memory Matters

Without shared memory, each agent call is isolated. The PM might define a feature, but the Dev agent would have no idea what was defined. Memory is the glue that holds the multi-agent system together.

### 4.2 Memory Architecture

The memory system has three storage layers, each optimised for a different type of information:

| Layer | Storage | Contains | Access Pattern |
|-------|---------|----------|----------------|
| Conversations | SQLite database | All messages between you and agents | Append-only, query by time or keyword |
| Tasks | JSON file | Task specs, statuses, assignments | Read/write, filtered by status |
| Context | Markdown files | Project summaries, architecture decisions, conventions | Read frequently, updated occasionally |

### 4.3 Folder Structure

```
nanoclaw/
  memory/
    conversations.db        # SQLite: all chat history
    tasks.json               # Current task states
    context/
      project_overview.md    # What the project is about
      architecture.md        # Technical decisions
      conventions.md         # Coding standards
      agent_notes.md         # Cross-agent observations
```

### 4.4 Conversation Memory (SQLite)

Every message — from you and from agents — is stored in an SQLite database. This allows agents to look back at what was discussed.

#### Database Schema

```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,        -- 'user', 'pm', 'dev', 'qa', 'system'
    agent TEXT,                -- which agent handled it
    content TEXT NOT NULL,     -- the actual message
    task_id TEXT,              -- related task (if any)
    metadata TEXT              -- JSON blob for extra info
);
```

#### How Memory Is Written

```python
async def save_message(self, role, agent, content, task_id=None):
    async with aiosqlite.connect(self.db_path) as db:
        await db.execute(
            'INSERT INTO conversations (timestamp, role, agent, content, task_id) '
            'VALUES (?, ?, ?, ?, ?)',
            (datetime.utcnow().isoformat(), role, agent, content, task_id)
        )
        await db.commit()
```

#### How Agents Read Memory

When an agent needs context, it retrieves the most recent relevant messages:

```python
async def get_recent(self, limit=20, task_id=None):
    query = 'SELECT * FROM conversations'
    params = []
    if task_id:
        query += ' WHERE task_id = ?'
        params.append(task_id)
    query += ' ORDER BY timestamp DESC LIMIT ?'
    params.append(limit)
    async with aiosqlite.connect(self.db_path) as db:
        rows = await db.execute(query, params)
        return await rows.fetchall()
```

### 4.5 Task Memory (JSON)

Tasks are stored in a simple JSON file. This format is chosen because it is human-readable (you can open it in any text editor) and easy for agents to parse.

#### Task Format

```json
{
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Add /health endpoint",
      "description": "Create a GET /health endpoint that returns 200 OK...",
      "status": "open",
      "priority": "high",
      "created_by": "pm",
      "assigned_to": "dev",
      "acceptance_criteria": [
        "Returns HTTP 200 with JSON body",
        "Includes uptime in response",
        "Has unit test coverage"
      ],
      "created_at": "2026-03-26T10:00:00Z",
      "updated_at": "2026-03-26T10:00:00Z"
    }
  ]
}
```

### 4.6 Context Memory (Markdown)

Context files are Markdown documents that summarise important project information. They are loaded into every agent prompt so that all agents share the same understanding of the project.

#### Example: project_overview.md

```markdown
# Project Overview

## What We Are Building
A REST API for a task management application.

## Tech Stack
- Backend: Python + FastAPI
- Database: PostgreSQL
- Auth: JWT tokens

## Current Status
- Basic CRUD endpoints: DONE
- Authentication: IN PROGRESS
- Frontend: NOT STARTED
```

### 4.7 Preventing Context Drift

Context drift happens when agents gradually develop conflicting understandings of the project. Here is how we prevent it:

- **Single Source of Truth:** Context files are the authoritative reference. Agents always read them before acting.
- **Summarisation:** After every 50 messages, the system generates a summary and appends it to the context files.
- **Conflict Detection:** Before the Dev agent implements something, it checks whether the spec in tasks.json matches the context files.
- **Manual Override:** You can always update context files directly by saying "@NanoClaw update context: we switched from PostgreSQL to SQLite."

---

## Phase 5 — Claude Code Integration

### 5.1 What Is Claude Code?

Claude Code is a command-line tool from Anthropic that allows Claude to read your files, write code, and run terminal commands directly on your Mac Mini. It is like having a developer sitting at your computer — except it is an AI.

### 5.2 How NanoClaw Triggers Claude Code

The Dev agent runs Claude Code as a subprocess. Here is the flow:

```
Discord message
    │
    ▼
Dev Agent constructs instructions
    │
    ▼
subprocess.run(['claude', '-p', instruction, '--output-format', 'json'])
    │
    ▼
Claude Code reads codebase, writes changes
    │
    ▼
Dev Agent parses output, reports back to Discord
```

### 5.3 Implementation

```python
import subprocess
import json
import os

class ClaudeCodeTool:
    def __init__(self, project_path):
        self.project_path = project_path

    async def execute(self, instruction, timeout=300):
        """Run Claude Code with an instruction on the project."""
        try:
            result = subprocess.run(
                [
                    'claude',
                    '-p', instruction,
                    '--output-format', 'json',
                    '--max-turns', '10',
                ],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, 'CLAUDE_CODE_ENTRYPOINT': 'nanoclaw'}
            )
            return self.parse_output(result.stdout)
        except subprocess.TimeoutExpired:
            return {'error': 'Claude Code timed out after 5 minutes'}

    def parse_output(self, raw):
        """Extract the meaningful response from Claude Code output."""
        try:
            data = json.loads(raw)
            return {
                'success': True,
                'response': data,
            }
        except json.JSONDecodeError:
            return {'success': True, 'response': raw}
```

### 5.4 Key Configuration

Claude Code needs a few things set up to work properly with NanoClaw:

- **ANTHROPIC_API_KEY:** Set in your shell environment or .env file.
- **Working Directory:** Always cd into the project folder before running Claude Code.
- **Timeout:** Set a 5-minute timeout to prevent runaway processes.
- **Max Turns:** Limit Claude Code to 10 turns per invocation to control costs.

> **Pro Tip:** Use the `--output-format json` flag so that Claude Code returns structured output that your Python code can parse reliably, rather than free-form text.

---

## Phase 6 — GitHub Integration

### 6.1 Setup

Your Mac Mini will have a local clone of your GitHub repository. NanoClaw agents interact with this local clone and push changes to GitHub.

#### Initial Setup Steps

1. Generate an SSH key on your Mac Mini: `ssh-keygen -t ed25519`
2. Add the public key to GitHub (Settings → SSH and GPG Keys)
3. Clone your repository: `git clone git@github.com:yourname/yourproject.git`
4. Verify it works: `cd yourproject && git pull`

### 6.2 Git Operations Module

```python
import git
from datetime import datetime

class GitTool:
    def __init__(self, repo_path):
        self.repo = git.Repo(repo_path)

    def create_branch(self, name):
        """Create and checkout a new feature branch."""
        branch_name = f'nanoclaw/{name}'
        self.repo.git.checkout('-b', branch_name)
        return branch_name

    def commit(self, message):
        """Stage all changes and commit."""
        self.repo.git.add('-A')
        self.repo.index.commit(f'[NanoClaw] {message}')
        return self.repo.head.commit.hexsha[:7]

    def push(self, branch=None):
        """Push to remote."""
        branch = branch or self.repo.active_branch.name
        origin = self.repo.remote('origin')
        origin.push(branch)
        return branch

    def create_pr(self, title, body):
        """Create a Pull Request via GitHub CLI."""
        import subprocess
        result = subprocess.run(
            ['gh', 'pr', 'create', '--title', title, '--body', body],
            cwd=self.repo.working_dir,
            capture_output=True, text=True
        )
        return result.stdout.strip()
```

### 6.3 Branch Strategy

NanoClaw uses a simple branching strategy to keep your main branch clean:

- **main:** Always stable. NanoClaw never pushes directly to main.
- **nanoclaw/feature-name:** Each feature gets its own branch, prefixed with `nanoclaw/` for easy identification.
- **Pull Requests:** After implementation, NanoClaw creates a PR so you can review before merging.

> **Safety:** The Dev agent is configured to NEVER force-push or push directly to main. All changes go through branches and PRs.

---

## Phase 7 — Discord UX Design

### 7.1 Command Format

All commands follow a consistent pattern:

```
@NanoClaw [AGENT] [INSTRUCTION]

Examples:
  @NanoClaw PM define a user login feature
  @NanoClaw Dev implement task TASK-001
  @NanoClaw QA test task TASK-001
  @NanoClaw status
  @NanoClaw help
```

### 7.2 Command Parser

```python
import re

AGENTS = {'pm': 'pm', 'dev': 'dev', 'qa': 'qa'}
ALIASES = {
    'product': 'pm', 'manager': 'pm',
    'developer': 'dev', 'code': 'dev', 'build': 'dev',
    'test': 'qa', 'quality': 'qa', 'check': 'qa',
}

def parse_command(message):
    text = message.strip()
    words = text.split(maxsplit=1)
    if not words:
        return {'agent': None, 'instruction': ''}

    first = words[0].lower()
    agent = AGENTS.get(first) or ALIASES.get(first)

    if agent:
        instruction = words[1] if len(words) > 1 else ''
        return {'agent': agent, 'instruction': instruction}
    else:
        return {'agent': 'orchestrator', 'instruction': text}
```

### 7.3 Response Formatting

NanoClaw formats responses with clear visual indicators so you can quickly see which agent replied and what happened:

```python
AGENT_EMOJIS = {
    'pm':  '📋',   # clipboard
    'dev': '💻',   # laptop
    'qa':  '✅',   # checkmark
    'system': '⚙️', # gear
}

def format_response(agent, content, task_id=None):
    emoji = AGENT_EMOJIS.get(agent, '🤖')
    header = f'{emoji} **{agent.upper()} Agent**'
    if task_id:
        header += f' | Task: `{task_id}`'
    return f'{header}\n\n{content}'
```

### 7.4 Discord Channel Structure

For best organisation, create dedicated channels in your Discord server:

| Channel | Purpose |
|---------|---------|
| #nanoclaw-commands | Where you send commands to agents |
| #nanoclaw-logs | Detailed execution logs and debug info |
| #nanoclaw-commits | Automatic notifications when code is pushed |
| #nanoclaw-general | Free-form discussion, questions, status checks |

### 7.5 Interactive Confirmations

For dangerous operations, the bot asks for confirmation using Discord reactions or buttons:

```
Bot: ⚠️ Dev Agent wants to delete 3 files and modify 12 files.
     Branch: nanoclaw/refactor-auth
     React ✅ to confirm or ❌ to cancel.
```

---

## Phase 8 — Multi-LLM Strategy

### 8.1 Why Multiple LLMs?

Different LLMs have different strengths and pricing. By routing tasks intelligently, you can reduce costs by 40–60% while maintaining quality. Not every task needs the most expensive model.

### 8.2 Routing Strategy

| Task Type | Recommended Model | Why |
|-----------|------------------|-----|
| Complex coding (new features) | Claude Sonnet / Opus | Best code generation quality |
| Code review and analysis | Claude Sonnet | Good reasoning at lower cost |
| Spec writing (PM tasks) | GPT-4o | Strong at structured text, cost-effective |
| Simple queries and status | Claude Haiku / GPT-4o-mini | Cheapest, fast, good enough |
| Test case generation | Claude Sonnet | Understands code well |
| Summarisation | Gemini Flash | Extremely cheap, handles long context |

### 8.3 LLM Router Implementation

```python
class LLMRouter:
    def __init__(self, config):
        self.anthropic = anthropic.Anthropic()
        self.openai_client = openai.OpenAI()
        self.config = config

    async def route(self, task_type, prompt, **kwargs):
        """Route to the best LLM based on task type."""
        model_map = {
            'coding':     ('anthropic', 'claude-sonnet-4-20250514'),
            'review':     ('anthropic', 'claude-sonnet-4-20250514'),
            'spec':       ('openai',    'gpt-4o'),
            'simple':     ('anthropic', 'claude-haiku-4-5-20251001'),
            'test':       ('anthropic', 'claude-sonnet-4-20250514'),
            'summarise':  ('openai',    'gpt-4o-mini'),
        }

        provider, model = model_map.get(task_type, ('anthropic', 'claude-sonnet-4-20250514'))

        if provider == 'anthropic':
            return await self._call_anthropic(model, prompt, **kwargs)
        elif provider == 'openai':
            return await self._call_openai(model, prompt, **kwargs)
```

### 8.4 Fallback Chain

If the primary LLM fails (rate limit, outage, error), the router automatically tries the next option:

```
Fallback chain:
  Claude Sonnet → GPT-4o → Gemini Pro → Claude Haiku

If all fail, the bot reports the error to Discord and retries in 60 seconds.
```

> **Cost Control:** Set monthly budget limits in your config.json. When spending approaches the limit, the router downgrades to cheaper models automatically. The bot will warn you in Discord when you hit 80% of your budget.

---

## Phase 9 — Step-by-Step Implementation

> **Time Estimate:** Following these steps at a comfortable pace should take 4–8 hours total. You do not need to do it all in one sitting.

### Step 1 — Create the Discord Bot

#### 1a. Create a Discord Application

1. Go to https://discord.com/developers/applications
2. Click "New Application" and name it "NanoClaw"
3. Go to the "Bot" tab on the left sidebar
4. Click "Reset Token" and copy the token — save it securely
5. Under "Privileged Gateway Intents," enable **Message Content Intent**
6. Go to "OAuth2" → "URL Generator"
7. Select scopes: `bot`, `applications.commands`
8. Select permissions: Send Messages, Read Messages, Add Reactions, Embed Links, Attach Files
9. Copy the generated URL and open it in your browser to invite the bot to your server

#### 1b. Create the Bot Script

```python
# bot.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!nc ', intents=intents)

@bot.event
async def on_ready():
    print(f'NanoClaw is online as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if bot.user.mentioned_in(message):
        # Remove the mention and parse the command
        content = message.content.replace(f'<@{bot.user.id}>', '').strip()
        await handle_command(message, content)
    await bot.process_commands(message)

async def handle_command(message, content):
    from orchestrator import Orchestrator
    orchestrator = Orchestrator()
    response = await orchestrator.process(content)
    await message.channel.send(response)

bot.run(os.getenv('DISCORD_TOKEN'))
```

### Step 2 — Set Up the Project Structure

Create the NanoClaw project folder on your Mac Mini:

```bash
mkdir -p ~/nanoclaw
cd ~/nanoclaw

# Create the folder structure
mkdir -p agents memory/context tools config logs

# Create initial files
touch bot.py orchestrator.py config/settings.json
touch agents/__init__.py agents/base.py agents/pm.py agents/dev.py agents/qa.py
touch tools/__init__.py tools/claude_code.py tools/git_tool.py tools/llm_router.py
touch memory/__init__.py memory/shared.py memory/tasks.json
touch memory/context/project_overview.md
touch .env requirements.txt
```

Your folder structure should now look like this:

```
nanoclaw/
├── bot.py                    # Discord bot entry point
├── orchestrator.py           # Command routing and coordination
├── .env                      # API keys (NEVER commit this)
├── requirements.txt          # Python dependencies
├── config/
│   └── settings.json         # Bot configuration
├── agents/
│   ├── __init__.py
│   ├── base.py               # BaseAgent class
│   ├── pm.py                 # Product Manager agent
│   ├── dev.py                # Developer agent
│   └── qa.py                 # QA agent
├── tools/
│   ├── __init__.py
│   ├── claude_code.py        # Claude Code CLI wrapper
│   ├── git_tool.py           # Git/GitHub operations
│   └── llm_router.py         # Multi-LLM routing
├── memory/
│   ├── __init__.py
│   ├── shared.py             # Memory manager
│   ├── tasks.json            # Task database
│   └── context/
│       ├── project_overview.md
│       └── conventions.md
└── logs/
    └── nanoclaw.log          # Application logs
```

### Step 3 — Configure Environment Variables

Create the `.env` file with your API keys:

```bash
# .env — NEVER commit this to Git!
DISCORD_TOKEN=your_discord_bot_token_here
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-your-openai-key-here      # Optional
GOOGLE_AI_API_KEY=your-google-key-here       # Optional

# Project configuration
PROJECT_PATH=/Users/yourusername/projects/yourproject
GITHUB_REPO=yourname/yourproject
```

### Step 4 — Build the Base Agent Class

This is the foundation that all agents inherit from:

```python
# agents/base.py
from tools.llm_router import LLMRouter
from memory.shared import SharedMemory

class BaseAgent:
    def __init__(self, name, system_prompt, task_type='coding'):
        self.name = name
        self.system_prompt = system_prompt
        self.task_type = task_type
        self.memory = SharedMemory()
        self.router = LLMRouter()

    async def handle(self, instruction, context=None):
        # Load relevant memory
        history = await self.memory.get_recent(limit=10)
        project_context = await self.memory.load_context()

        # Build the full prompt
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': self._build_user_prompt(
                instruction, history, project_context, context
            )}
        ]

        # Call the LLM through the router
        response = await self.router.route(
            task_type=self.task_type,
            messages=messages
        )

        # Save to memory
        await self.memory.save_message(
            role=self.name,
            agent=self.name,
            content=response
        )

        return response

    def _build_user_prompt(self, instruction, history, context, extra):
        parts = []
        if context:
            parts.append(f'Project Context:\n{context}')
        if history:
            parts.append(f'Recent History:\n{history}')
        if extra:
            parts.append(f'Additional Context:\n{extra}')
        parts.append(f'Instruction:\n{instruction}')
        return '\n\n---\n\n'.join(parts)
```

### Step 5 — Build the Orchestrator

```python
# orchestrator.py
from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent

class Orchestrator:
    def __init__(self):
        self.agents = {
            'pm': PMAgent(),
            'dev': DevAgent(),
            'qa': QAAgent(),
        }
        self.aliases = {
            'product': 'pm', 'manager': 'pm', 'spec': 'pm',
            'developer': 'dev', 'code': 'dev', 'build': 'dev', 'implement': 'dev',
            'test': 'qa', 'quality': 'qa', 'check': 'qa', 'verify': 'qa',
        }

    async def process(self, content):
        parsed = self._parse(content)
        agent_key = parsed['agent']

        if agent_key == 'status':
            return await self._get_status()
        if agent_key == 'help':
            return self._get_help()

        agent = self.agents.get(agent_key)
        if not agent:
            return f'Unknown agent: {agent_key}. Use PM, Dev, or QA.'

        try:
            return await agent.handle(parsed['instruction'])
        except Exception as e:
            return f'Error: {str(e)}'

    def _parse(self, content):
        words = content.strip().split(maxsplit=1)
        if not words:
            return {'agent': 'help', 'instruction': ''}
        first = words[0].lower().rstrip(',:')
        instruction = words[1] if len(words) > 1 else ''
        # Check direct agent names
        if first in self.agents:
            return {'agent': first, 'instruction': instruction}
        # Check aliases
        if first in self.aliases:
            return {'agent': self.aliases[first], 'instruction': instruction}
        # Special commands
        if first in ('status', 'help'):
            return {'agent': first, 'instruction': ''}
        # Default: send full message to dev
        return {'agent': 'dev', 'instruction': content}
```

### Step 6 — Connect Claude Code

Wire up the Claude Code tool so the Dev agent can execute code changes (see Phase 5 for the full `ClaudeCodeTool` class). Then add it to the Dev agent:

```python
# agents/dev.py
from agents.base import BaseAgent
from tools.claude_code import ClaudeCodeTool
from tools.git_tool import GitTool
import os

class DevAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name='dev',
            system_prompt=DEV_SYSTEM_PROMPT,
            task_type='coding'
        )
        project_path = os.getenv('PROJECT_PATH')
        self.claude_code = ClaudeCodeTool(project_path)
        self.git = GitTool(project_path)

    async def handle(self, instruction, context=None):
        # Use Claude Code for implementation tasks
        if any(kw in instruction.lower() for kw in
               ['implement', 'build', 'create', 'add', 'fix', 'modify']):
            result = await self.claude_code.execute(instruction)
            if result.get('success'):
                # Auto-commit the changes
                commit_hash = self.git.commit(f'feat: {instruction[:50]}')
                branch = self.git.push()
                return (
                    f'Implementation complete.\n'
                    f'Commit: `{commit_hash}`\n'
                    f'Branch: `{branch}`'
                )
            return f'Error: {result.get("error", "Unknown error")}'

        # For non-coding tasks, use the base handler
        return await super().handle(instruction, context)
```

### Step 7 — Install and Run

1. Install Python dependencies:

```bash
cd ~/nanoclaw
pip install -r requirements.txt
```

2. Test the bot locally:

```bash
python bot.py
```

3. Verify in Discord: type `@NanoClaw help` in your server

4. Test a simple command: `@NanoClaw Dev list the files in this project`

### Step 8 — Set Up Auto-Start (launchd)

Make NanoClaw start automatically when your Mac Mini boots:

```bash
# Create a launch agent plist
cat > ~/Library/LaunchAgents/com.nanoclaw.bot.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.nanoclaw.bot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/python3</string>
    <string>/Users/YOURUSERNAME/nanoclaw/bot.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOURUSERNAME/nanoclaw</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/YOURUSERNAME/nanoclaw/logs/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOURUSERNAME/nanoclaw/logs/stderr.log</string>
</dict>
</plist>
EOF

# Load the agent
launchctl load ~/Library/LaunchAgents/com.nanoclaw.bot.plist
```

---

## Phase 10 — End-to-End Workflow Example

Here is a complete example showing how you would use NanoClaw to add a user login feature to your project, from idea to deployed code.

### 10.1 Step-by-Step Walkthrough

#### You define the feature

```
You: @NanoClaw PM define a user login feature with
     email/password, JWT tokens, and a /me endpoint
```

#### PM Agent responds

```
📋 PM Agent:

Feature: User Authentication
Description: Email/password login with JWT token-based sessions.

Tasks created:
  TASK-042: Create User model with email/password fields | HIGH
  TASK-043: Implement POST /auth/register endpoint      | HIGH
  TASK-044: Implement POST /auth/login endpoint          | HIGH
  TASK-045: Add JWT token generation and validation       | HIGH
  TASK-046: Create GET /auth/me endpoint                  | MEDIUM
  TASK-047: Add password hashing with bcrypt              | HIGH

Acceptance Criteria:
  [ ] Users can register with email and password
  [ ] Passwords are hashed, never stored in plain text
  [ ] Login returns a JWT token
  [ ] /me endpoint returns user profile when authenticated
  [ ] Invalid tokens return 401 Unauthorized
```

#### You tell Dev to implement

```
You: @NanoClaw Dev implement TASK-042 through TASK-047
```

#### Dev Agent works

```
💻 Dev Agent:

Working on user authentication...

Branch created: nanoclaw/feature-user-auth

Progress:
  [Done] TASK-042: Created User model in models/user.py
  [Done] TASK-043: Added /auth/register in routes/auth.py
  [Done] TASK-044: Added /auth/login in routes/auth.py
  [Done] TASK-045: JWT utils in utils/jwt.py
  [Done] TASK-046: Added /auth/me in routes/auth.py
  [Done] TASK-047: bcrypt hashing in models/user.py

Commit: a1b2c3d
Branch: nanoclaw/feature-user-auth
Files changed: 6 added, 2 modified
```

#### You ask QA to validate

```
You: @NanoClaw QA test the user auth feature
```

#### QA Agent tests

```
✅ QA Agent:

Running tests for user authentication...

Test Results: 8 passed, 1 failed

  PASS: Register with valid email/password
  PASS: Register rejects duplicate email
  PASS: Login with correct credentials returns JWT
  PASS: Login with wrong password returns 401
  PASS: /me returns profile with valid token
  PASS: /me returns 401 with invalid token
  PASS: Passwords are hashed in database
  PASS: JWT tokens expire after configured time
  FAIL: Register does not validate email format

Bug filed: TASK-048 - Add email format validation
Recommendation: Fix TASK-048 before merging to main.
```

#### You approve and merge

```
You: @NanoClaw Dev fix TASK-048 then create a PR

💻 Dev Agent:
  Fixed email validation. Commit: d4e5f6g
  PR created: https://github.com/you/project/pull/12
  Title: "Add user authentication with JWT"
```

---

## Phase 11 — Safety & Control

### 11.1 Confirmation Gates

Certain operations require your explicit approval before they execute:

| Operation | Gate Type | Why |
|-----------|-----------|-----|
| Deleting files | Reaction confirmation | Prevents accidental data loss |
| Pushing to GitHub | Auto (but never to main) | Speed, with branch protection safety |
| Merging PRs | Reaction confirmation | Human review before main branch changes |
| Modifying .env or config | Reaction confirmation | Could break the system |
| Running shell commands | Reaction confirmation | Arbitrary execution is risky |

### 11.2 Logging

Every action is logged to both a file and the #nanoclaw-logs Discord channel:

```python
# Logging configuration
import logging

logger = logging.getLogger('nanoclaw')
logger.setLevel(logging.INFO)

# File handler
fh = logging.FileHandler('logs/nanoclaw.log')
fh.setFormatter(logging.Formatter(
    '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
))
logger.addHandler(fh)
```

### 11.3 Rate Limiting

Protect against runaway costs and accidental loops:

- **Max 30 LLM calls per hour:** Prevents infinite loops from consuming your API budget.
- **Max 10 Claude Code executions per hour:** Each execution can be expensive.
- **Max 5 Git pushes per hour:** Prevents spamming your repository.
- **Cool-down period:** If limits are hit, the bot pauses for 10 minutes and notifies you.

### 11.4 Emergency Stop

If something goes wrong, you can instantly stop all agent activity:

```
You: @NanoClaw STOP

Bot: ⛔ All agents paused. No operations will execute.
     Type @NanoClaw RESUME to continue.
```

---

## Phase 12 — Future Extensions

### 12.1 DevOps Agent

Once your coding pipeline is stable, add a DevOps agent to handle deployment:

- **Capabilities:** Build Docker images, deploy to servers, manage environment variables, monitor health checks.
- **Tools:** Docker CLI, SSH, cloud provider CLIs (AWS, GCP, DigitalOcean).
- **Trigger:** `@NanoClaw DevOps deploy latest to staging`

### 12.2 CI/CD Integration

Connect NanoClaw to GitHub Actions so that every PR automatically triggers tests:

- On PR creation, GitHub Actions runs the test suite
- Results are posted back to the Discord #nanoclaw-commits channel
- QA agent can interpret CI results and suggest fixes

### 12.3 Vector Database for Memory

As your project grows, the simple SQLite + JSON memory may not scale. Upgrade to a vector database to enable semantic search over project history:

- **Option 1 — ChromaDB:** Runs locally, no server needed, Python-native. Great starting point.
- **Option 2 — Qdrant:** More powerful, runs as Docker container, better for large projects.

### 12.4 Kubernetes Deployment

For team use or high availability, containerise NanoClaw and deploy on Kubernetes:

```
nanoclaw-cluster/
  ├── bot-deployment.yaml          # Discord bot pod
  ├── agent-workers-deployment.yaml # Agent processing pods
  ├── memory-statefulset.yaml       # Persistent memory storage
  ├── redis-deployment.yaml          # Message queue between pods
  └── ingress.yaml                  # External access (optional)
```

### 12.5 Local LLMs via Docker

For ultimate cost control or offline use, run open-source LLMs locally using Ollama:

```bash
# Install Ollama on Mac Mini
brew install ollama

# Pull a coding model
ollama pull codellama:34b

# Run as a server
ollama serve

# Add to your LLM router as a local provider
# endpoint: http://localhost:11434/api/chat
```

> **Scaling Path:** Start with the simple setup in this guide. Only add Docker, Kubernetes, or vector databases when you actually need them. Premature complexity is the enemy of productivity.

### 12.6 Roadmap Summary

| Phase | What to Add | When |
|-------|------------|------|
| Now | Core system (Discord + 3 agents + Claude Code + GitHub) | First week |
| Month 1 | Polish UX, tune prompts, add error handling | After basic system works |
| Month 2 | DevOps agent, CI/CD integration | When you start deploying |
| Month 3+ | Vector memory, local LLMs, Kubernetes | When team grows or costs rise |

---

## Appendix A — Complete Folder Structure

```
nanoclaw/
├── bot.py                        # Main entry point: Discord bot
├── orchestrator.py               # Routes commands to agents
├── .env                          # API keys (gitignored)
├── .gitignore                    # Excludes .env, logs, __pycache__
├── requirements.txt              # Python dependencies
├── README.md                     # Project documentation
│
├── config/
│   ├── settings.json             # Runtime configuration
│   └── prompts/                  # Agent system prompts
│       ├── pm_prompt.md
│       ├── dev_prompt.md
│       └── qa_prompt.md
│
├── agents/
│   ├── __init__.py
│   ├── base.py                   # BaseAgent with shared logic
│   ├── pm.py                     # Product Manager agent
│   ├── dev.py                    # Developer agent
│   └── qa.py                     # Quality Assurance agent
│
├── tools/
│   ├── __init__.py
│   ├── claude_code.py            # Claude Code CLI integration
│   ├── git_tool.py               # Git and GitHub operations
│   └── llm_router.py             # Multi-LLM routing logic
│
├── memory/
│   ├── __init__.py
│   ├── shared.py                 # SharedMemory class
│   ├── conversations.db          # SQLite (auto-created)
│   ├── tasks.json                # Task state database
│   └── context/                  # Project knowledge base
│       ├── project_overview.md
│       ├── architecture.md
│       └── conventions.md
│
└── logs/
    ├── nanoclaw.log              # Application log
    ├── stdout.log                # Process stdout
    └── stderr.log                # Process stderr
```

---

## Appendix B — Troubleshooting Guide

| Problem | Cause | Solution |
|---------|-------|---------|
| Bot appears offline in Discord | Process crashed or not running | Check logs/stderr.log. Run: `launchctl list \| grep nanoclaw` |
| Bot does not respond to messages | Message Content Intent not enabled | Go to Discord Developer Portal → Bot → Enable Message Content Intent |
| Claude Code times out | Complex task or large codebase | Increase timeout in claude_code.py. Break task into smaller pieces |
| Git push fails | SSH key not configured | Run: `ssh -T git@github.com` to test. Add key if needed |
| API returns 401 Unauthorized | Invalid or expired API key | Regenerate key and update .env file. Restart bot |
| Rate limit errors | Too many API calls | Check rate_limit config in settings.json. Reduce call frequency |
| Agent gives wrong context | Memory not loading properly | Check conversations.db exists. Verify SQLite queries in shared.py |
| Bot sends empty responses | LLM returned empty response | Check logs for API errors. Verify model name is correct |

---

## Getting Help

If you get stuck at any point:

- Check the logs folder for error messages
- Ask Claude (or NanoClaw itself once running) to debug the issue
- The Discord.py documentation is at https://discordpy.readthedocs.io
- The Anthropic API documentation is at https://docs.anthropic.com

**You are building something powerful.** Start simple, get the basic loop working (Discord → Agent → Claude Code → GitHub), and then iterate from there. Good luck!
