---
title: CTO Assistant Agent
date: 2026-04-23
status: approved
---

# CTO Assistant Agent — Design Spec

## Problem

NanoClaw's current entry point (`Orchestrator`) requires exact keyword syntax. Any message that doesn't start with `pm`, `dev`, `feature`, `build`, `implement`, `status`, `cost`, `stop`, or `resume` returns a usage message. There is no natural language understanding layer.

Users must know the command vocabulary. Free-text inputs like *"fix the login bug"* or *"why is auth slow?"* silently fail.

---

## Goal

Add a natural language interface layer — `CTOAgent` — that sits between the Discord bot and the existing `Orchestrator`. Users can speak freely; the agent classifies intent and routes appropriately. Existing components are not modified.

---

## Architecture

```
Discord message
    ↓
bot._handle_message()
    ↓
CTOAgent.process(raw_message, session_id)
    ↓  one LLM call (claude-haiku — cheap, fast)
    ↓  returns CTODecision
    ↓
┌─────────────────────────────────────────────┐
│ decision.action                             │
│  "execute"  → orchestrator.handle(command)  │
│  "respond"  → post direct_response          │
│  "clarify"  → post one question             │
└─────────────────────────────────────────────┘
```

### What changes

| File | Change |
|------|--------|
| `agents/cto_agent.py` | **New** — CTOAgent class |
| `config/prompts/cto_prompt.md` | **New** — persona + JSON output rules |
| `bot.py` | **Modified** — init CTOAgent, swap `_handle_message` routing, replace `_is_task_command` |
| `config/settings.json` | **Modified** — add `"cto"` route → haiku model |

### What does NOT change

`Orchestrator`, `WorkflowEngine`, `PMAgent`, `DevAgent`, `QAAgent`, all safety/memory/tool layers — untouched.

---

## CTODecision Data Model

```python
@dataclass
class CTODecision:
    action: str          # "execute" | "respond" | "clarify"
    command: str | None  # synthesized orchestrator command (action=execute only)
    response: str | None # direct answer text (action=respond only)
    question: str | None # one clarifying question (action=clarify only)
    intent: str          # "coding" | "debugging" | "planning" | "analysis" | "system" | "unclear"
    confidence: float    # 0.0–1.0
    reasoning: str       # internal note, not shown to user
```

---

## Intent Classification

The CTO prompt instructs the LLM to analyse the message and return a `CTODecision` as JSON.

### Intent → Action Mapping

| Intent | Action | Synthesized command |
|--------|--------|---------------------|
| `coding` | execute | `feature <instruction>` |
| `debugging` | execute | `feature debug: <description>` |
| `planning` | execute | `pm define <instruction>` |
| `system` | execute | `status` / `cost` / `stop` / `resume` |
| `analysis` | respond | direct LLM answer (no execution) |
| `unclear` + confidence < 0.6 | clarify | one focused question |
| `unclear` + confidence ≥ 0.6 | execute or respond | best-effort interpretation |

### Examples

| User message | Intent | Action | Command |
|---|---|---|---|
| "fix the login bug" | coding | execute | `feature fix login bug` |
| "why is auth slow?" | analysis | respond | — |
| "add caching maybe?" | coding | execute | `feature add caching layer` |
| "how much have we spent?" | system | execute | `cost` |
| "something feels off" | unclear (0.3) | clarify | "Can you describe what's behaving unexpectedly?" |
| "make it better" | unclear (0.2) | clarify | "Which part — performance, UX, or something specific?" |
| "stop everything" | system | clarify | "Confirm: stop the job queue? React ✅ to confirm." |

---

## CTO Agent Class (`agents/cto_agent.py`)

```python
CTOAgent(BaseAgent)
  name        = "cto"
  task_type   = "cto"
  prompt_file = "config/prompts/cto_prompt.md"

  async process(message: str, session_id: str) -> CTODecision
    # Calls BaseAgent.handle() → gets raw LLM response
    # Calls _parse_decision() → returns CTODecision

  def _parse_decision(raw: str) -> CTODecision
    # Parse JSON from LLM response
    # On malformed JSON → return clarify fallback
    # On destructive command → downgrade to clarify with confirmation
```

### Destructive command guard

If `action=execute` and synthesized command contains `STOP`, `delete`, `drop`, or `reset`, the decision is downgraded to `clarify` with a confirmation question before passing to orchestrator.

---

## CTO Prompt (`config/prompts/cto_prompt.md`)

**Persona rules:**
- Pragmatic CTO assistant — understands both business and technical context
- Slightly opinionated, concise, not robotic
- Never verbose; `respond` answers are 2–4 sentences max

**Output rules (strict):**
- Always return valid JSON matching the `CTODecision` schema
- No prose, no markdown fences around JSON
- `command` must be a valid orchestrator command string when `action=execute`
- `question` must be a single sentence when `action=clarify`
- `confidence` must be a float between 0.0 and 1.0

---

## Bot Integration (`bot.py` changes)

### `__init__` — add CTOAgent

```python
self.cto = CTOAgent(self.router, self.memory, self.context_loader)
```

### `_handle_message` — swap routing

`session_id` is tied to the Discord thread ID when a thread exists (enables multi-message context continuity), otherwise a new UUID is generated per message.

```python
# Before:
response = await self.orchestrator.handle(command, ...)

# After:
session_id = str(thread.id) if thread else str(uuid.uuid4())
decision = await self.cto.process(command, session_id)

if decision.action == "execute":
    response = await self.orchestrator.handle(decision.command, ...)
elif decision.action == "respond":
    response = decision.response
elif decision.action == "clarify":
    response = decision.question
```

### Thread creation — use decision instead of keyword matching

```python
# Before: self._is_task_command(command)
# After:  decision.action == "execute"
```

### Fallback on CTOAgent failure

If `cto.process()` raises any exception, fall through to `orchestrator.handle(command)` directly — raw keyword parsing remains functional as a safety net.

---

## Settings (`config/settings.json`)

Add to `llm.routing`:

```json
"cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}
```

Haiku is sufficient for JSON classification. Cost is ~$0.001 per message — negligible.

---

## Safety Considerations

| Risk | Mitigation |
|------|-----------|
| Destructive command executed without confirmation | Downgrade to `clarify` if command contains `STOP`, `delete`, `drop`, `reset` |
| LLM returns malformed JSON | `_parse_decision` catches exception → returns `clarify` fallback |
| CTOAgent LLM call times out or fails | `try/except` in `_handle_message` → falls back to `orchestrator.handle(raw_command)` |
| Non-allowed user message | Auth check in `bot._handle_message` runs before CTOAgent — unchanged |
| Hallucinated orchestrator command | Orchestrator's own parser returns `_usage()` for invalid commands — safe |

---

## Improvements Over Current System

| Before | After |
|--------|-------|
| "fix login bug" → usage message | "fix login bug" → `feature fix login bug` |
| Must know exact command syntax | Free text accepted |
| Analysis questions ignored | Answered directly by CTO persona |
| Thread creation tied to keyword prefix | Thread creation tied to intent (execute) |
| Single entry point with no context | CTO Agent carries session history via SharedMemory |

---

## Out of Scope

- Terminal/iTerm integration — execution happens via existing `ClaudeCodeTool` subprocess, no new terminal layer needed
- Multi-turn clarification loops — one clarifying question per message; next message starts fresh
- CTO Agent learning from past tasks — memory is session-scoped (existing SharedMemory behaviour)
- Replacing orchestrator — it remains fully functional for users who prefer explicit commands
