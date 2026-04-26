# CTO Assistant Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a natural language interface layer (`CTOAgent`) that sits between the Discord bot and the existing `Orchestrator`, classifying free-text user messages into execute/respond/clarify decisions using an LLM.

**Architecture:** `CTOAgent` extends `BaseAgent` and adds a `process()` method that calls the LLM with a JSON-enforcing prompt, parses the response into a `CTODecision` dataclass, and applies a destructive-command guard before returning. `bot._handle_message()` is updated to call `cto.process()` first and route based on the decision, with full fallback to raw orchestrator on any failure.

**Tech Stack:** Python 3.11+, pytest-asyncio, existing `BaseAgent` / `LLMRouter` / `SharedMemory` / `ContextLoader` stack, `discord.py`, Pydantic (already in use for settings).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `nanoclaw/agents/cto_agent.py` | **Create** | `CTODecision` dataclass, `CTOAgent` class, `_parse_decision`, destructive guard |
| `nanoclaw/config/prompts/cto_prompt.md` | **Create** | CTO persona + JSON schema instructions for the LLM |
| `nanoclaw/tests/test_cto_agent.py` | **Create** | Unit tests for `CTOAgent` and `CTODecision` parsing |
| `nanoclaw/config/settings.json` | **Modify** | Add `"cto"` entry to `llm.routing` |
| `nanoclaw/tests/conftest.py` | **Modify** | Add `"cto"` to `SAMPLE_SETTINGS` routing dict |
| `nanoclaw/bot.py` | **Modify** | Import + init `CTOAgent`, swap `_handle_message` routing, replace `_is_task_command` |

---

## Task 1: CTODecision dataclass and JSON parser

**Files:**
- Create: `nanoclaw/agents/cto_agent.py`
- Create: `nanoclaw/tests/test_cto_agent.py`

### What this task produces

A `CTODecision` dataclass and a static `_parse_decision(raw: str) -> CTODecision` method that extracts it from an LLM response string. No LLM calls yet — pure parsing logic.

---

- [ ] **Step 1: Write the failing tests**

Create `nanoclaw/tests/test_cto_agent.py`:

```python
"""Tests for CTOAgent — decision parsing, process(), and bot integration."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.cto_agent import CTOAgent, CTODecision


# --- CTODecision parsing ---

def test_parse_decision_valid_execute():
    raw = json.dumps({
        "action": "execute",
        "command": "feature fix login bug",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "user wants to fix a bug"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "execute"
    assert decision.command == "feature fix login bug"
    assert decision.intent == "coding"
    assert decision.confidence == 0.9


def test_parse_decision_valid_respond():
    raw = json.dumps({
        "action": "respond",
        "command": None,
        "response": "Auth is slow because of N+1 queries in the user lookup.",
        "question": None,
        "intent": "analysis",
        "confidence": 0.85,
        "reasoning": "analysis question"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "respond"
    assert "N+1" in decision.response
    assert decision.command is None


def test_parse_decision_valid_clarify():
    raw = json.dumps({
        "action": "clarify",
        "command": None,
        "response": None,
        "question": "Can you describe what's behaving unexpectedly?",
        "intent": "unclear",
        "confidence": 0.3,
        "reasoning": "too vague"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
    assert decision.question == "Can you describe what's behaving unexpectedly?"


def test_parse_decision_malformed_json_returns_clarify_fallback():
    raw = "Sorry, I can't help with that."
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
    assert decision.question is not None
    assert len(decision.question) > 0


def test_parse_decision_json_with_prose_wrapper():
    # LLM sometimes wraps JSON in prose — parser should still extract it
    raw = 'Here is my analysis:\n' + json.dumps({
        "action": "execute",
        "command": "status",
        "response": None,
        "question": None,
        "intent": "system",
        "confidence": 0.95,
        "reasoning": "status check"
    }) + '\nEnd.'
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "execute"
    assert decision.command == "status"


def test_parse_decision_missing_fields_returns_clarify_fallback():
    # Valid JSON but missing required fields
    raw = json.dumps({"action": "execute"})
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.cto_agent'`

- [ ] **Step 3: Create `nanoclaw/agents/cto_agent.py` with CTODecision and _parse_decision**

```python
"""CTOAgent — natural language interface layer for NanoClaw."""
import json
import logging
import re
from dataclasses import dataclass

from agents.base import BaseAgent

logger = logging.getLogger("nanoclaw.agents.cto")

_CLARIFY_FALLBACK = CTODecision = None  # defined below


@dataclass
class CTODecision:
    action: str           # "execute" | "respond" | "clarify"
    command: str | None   # orchestrator command string (action=execute only)
    response: str | None  # direct answer (action=respond only)
    question: str | None  # one clarifying question (action=clarify only)
    intent: str           # "coding"|"debugging"|"planning"|"analysis"|"system"|"unclear"
    confidence: float     # 0.0–1.0
    reasoning: str        # internal note, not shown to user


_FALLBACK_DECISION = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="I didn't quite follow that — could you rephrase or give me more detail?",
    intent="unclear",
    confidence=0.0,
    reasoning="parse failure",
)


class CTOAgent(BaseAgent):
    name = "cto"
    task_type = "cto"
    prompt_file = "config/prompts/cto_prompt.md"

    @staticmethod
    def _parse_decision(raw: str) -> CTODecision:
        """Parse LLM response into a CTODecision. Returns clarify fallback on any error."""
        # Strip markdown fences if present
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # Extract JSON object if wrapped in prose
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("CTOAgent: no JSON object found in response")
            return _FALLBACK_DECISION

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("CTOAgent: JSON parse error: %s", e)
            return _FALLBACK_DECISION

        required = {"action", "command", "response", "question",
                    "intent", "confidence", "reasoning"}
        if not required.issubset(data.keys()):
            logger.warning("CTOAgent: missing fields in decision: %s",
                           required - data.keys())
            return _FALLBACK_DECISION

        try:
            return CTODecision(
                action=str(data["action"]),
                command=data["command"],
                response=data["response"],
                question=data["question"],
                intent=str(data["intent"]),
                confidence=float(data["confidence"]),
                reasoning=str(data["reasoning"]),
            )
        except (TypeError, ValueError) as e:
            logger.warning("CTOAgent: field type error: %s", e)
            return _FALLBACK_DECISION
```

- [ ] **Step 4: Run parsing tests — all should pass**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py -v -k "parse"
```

Expected:
```
tests/test_cto_agent.py::test_parse_decision_valid_execute PASSED
tests/test_cto_agent.py::test_parse_decision_valid_respond PASSED
tests/test_cto_agent.py::test_parse_decision_valid_clarify PASSED
tests/test_cto_agent.py::test_parse_decision_malformed_json_returns_clarify_fallback PASSED
tests/test_cto_agent.py::test_parse_decision_json_with_prose_wrapper PASSED
tests/test_cto_agent.py::test_parse_decision_missing_fields_returns_clarify_fallback PASSED
```

- [ ] **Step 5: Commit**

```bash
git add nanoclaw/agents/cto_agent.py nanoclaw/tests/test_cto_agent.py
git commit -m "feat(cto-agent): add CTODecision dataclass and JSON parser"
```

---

## Task 2: CTOAgent.process() and destructive command guard

**Files:**
- Modify: `nanoclaw/agents/cto_agent.py`
- Modify: `nanoclaw/tests/test_cto_agent.py`

### What this task produces

`CTOAgent.process()` — calls `BaseAgent.handle()`, parses the result, and applies the destructive-command guard before returning.

---

- [ ] **Step 1: Add process() tests and destructive guard tests**

Append to `nanoclaw/tests/test_cto_agent.py`:

```python
# --- Shared agent helpers (reuse pattern from test_agents.py) ---

from tools.providers.base import LLMResponse


def make_router(response_content="{}"):
    router = MagicMock()
    router.route = AsyncMock(return_value=LLMResponse(
        content=response_content,
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
        tokens_in=50,
        tokens_out=30,
        cost_usd=0.0001,
    ))
    return router


def make_memory():
    memory = MagicMock()
    memory.get_recent = AsyncMock(return_value=[])
    memory.save_message = AsyncMock()
    return memory


def make_context():
    context = MagicMock()
    context.load_all = AsyncMock(return_value="# Project context")
    return memory


def make_cto_agent(llm_response: str) -> CTOAgent:
    return CTOAgent(make_router(llm_response), make_memory(), make_context())


# --- process() ---

@pytest.mark.asyncio
async def test_process_returns_execute_decision():
    llm_json = json.dumps({
        "action": "execute",
        "command": "feature fix login bug",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "bug fix"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("fix the login bug", session_id="s1")
    assert decision.action == "execute"
    assert decision.command == "feature fix login bug"


@pytest.mark.asyncio
async def test_process_returns_respond_decision():
    llm_json = json.dumps({
        "action": "respond",
        "command": None,
        "response": "Auth is slow due to missing indexes.",
        "question": None,
        "intent": "analysis",
        "confidence": 0.88,
        "reasoning": "analysis"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("why is auth slow?", session_id="s1")
    assert decision.action == "respond"
    assert "indexes" in decision.response


@pytest.mark.asyncio
async def test_process_uses_session_id():
    llm_json = json.dumps({
        "action": "execute", "command": "status",
        "response": None, "question": None,
        "intent": "system", "confidence": 0.95, "reasoning": "status"
    })
    agent = make_cto_agent(llm_json)
    await agent.process("how are we doing?", session_id="thread-abc")
    call_kwargs = agent.router.route.call_args.kwargs
    assert call_kwargs["session_id"] == "thread-abc"


# --- Destructive command guard ---

@pytest.mark.asyncio
async def test_destructive_stop_command_is_downgraded_to_clarify():
    llm_json = json.dumps({
        "action": "execute",
        "command": "STOP",
        "response": None,
        "question": None,
        "intent": "system",
        "confidence": 0.9,
        "reasoning": "stop queue"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("stop everything", session_id="s1")
    assert decision.action == "clarify"
    assert decision.question is not None


@pytest.mark.asyncio
async def test_destructive_delete_command_is_downgraded_to_clarify():
    llm_json = json.dumps({
        "action": "execute",
        "command": "feature delete all tasks",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.8,
        "reasoning": "delete"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("delete everything", session_id="s1")
    assert decision.action == "clarify"


@pytest.mark.asyncio
async def test_non_destructive_command_passes_through():
    llm_json = json.dumps({
        "action": "execute",
        "command": "feature add health endpoint",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "add feature"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("add a health endpoint", session_id="s1")
    assert decision.action == "execute"
    assert decision.command == "feature add health endpoint"


@pytest.mark.asyncio
async def test_process_fallback_on_llm_failure():
    agent = CTOAgent(make_router(), make_memory(), make_context())
    agent.router.route = AsyncMock(side_effect=Exception("LLM timeout"))
    decision = await agent.process("do something", session_id="s1")
    assert decision.action == "clarify"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py -v -k "process or destructive or guard" 2>&1 | tail -20
```

Expected: `AttributeError: type object 'CTOAgent' has no attribute 'process'`

- [ ] **Step 3: Fix the make_context helper (typo in test file)**

In `test_cto_agent.py`, find `make_context` — it has a bug (`return memory` instead of `return context`). Fix:

```python
def make_context():
    context = MagicMock()
    context.load_all = AsyncMock(return_value="# Project context")
    return context  # was incorrectly returning memory
```

- [ ] **Step 4: Implement process() and destructive guard in cto_agent.py**

Add these methods to the `CTOAgent` class in `nanoclaw/agents/cto_agent.py`:

```python
_DESTRUCTIVE_KEYWORDS = frozenset({"stop", "delete", "drop", "reset"})

_DESTRUCTIVE_CLARIFY = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="That looks like a destructive action — can you confirm exactly what you want to do?",
    intent="unclear",
    confidence=1.0,
    reasoning="destructive command guard triggered",
)


class CTOAgent(BaseAgent):
    # ... existing class attributes ...

    async def process(self, message: str, session_id: str) -> CTODecision:
        """Classify message intent via LLM and return a routing decision."""
        try:
            raw = await self.handle(message, session_id=session_id)
        except Exception as e:
            logger.error("CTOAgent LLM call failed: %s", e)
            return _FALLBACK_DECISION

        decision = self._parse_decision(raw)
        return self._apply_destructive_guard(decision)

    @staticmethod
    def _apply_destructive_guard(decision: CTODecision) -> CTODecision:
        """Downgrade execute decisions that contain destructive keywords to clarify."""
        if decision.action != "execute" or not decision.command:
            return decision
        command_words = set(decision.command.lower().split())
        if command_words & _DESTRUCTIVE_KEYWORDS:
            logger.info("CTOAgent: destructive guard triggered for command: %s",
                        decision.command)
            return _DESTRUCTIVE_CLARIFY
        return decision
```

Note: `_DESTRUCTIVE_KEYWORDS`, `_DESTRUCTIVE_CLARIFY`, and `_FALLBACK_DECISION` must be defined at module level, before the class, since they are referenced in static methods. Move `_FALLBACK_DECISION` definition to after `CTODecision` is defined, and add the new constants alongside it:

```python
# Module-level constants (after CTODecision dataclass definition)

_FALLBACK_DECISION = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="I didn't quite follow that — could you rephrase or give me more detail?",
    intent="unclear",
    confidence=0.0,
    reasoning="parse failure",
)

_DESTRUCTIVE_CLARIFY = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="That looks like a destructive action — can you confirm exactly what you want to do?",
    intent="unclear",
    confidence=1.0,
    reasoning="destructive command guard triggered",
)

_DESTRUCTIVE_KEYWORDS = frozenset({"stop", "delete", "drop", "reset"})
```

Also remove the broken forward-reference placeholder `_CLARIFY_FALLBACK = CTODecision = None` from the top of the file (it was a placeholder, replace the full file now):

Full final `nanoclaw/agents/cto_agent.py`:

```python
"""CTOAgent — natural language interface layer for NanoClaw."""
import json
import logging
import re
from dataclasses import dataclass

from agents.base import BaseAgent

logger = logging.getLogger("nanoclaw.agents.cto")


@dataclass
class CTODecision:
    action: str           # "execute" | "respond" | "clarify"
    command: str | None   # orchestrator command string (action=execute only)
    response: str | None  # direct answer (action=respond only)
    question: str | None  # one clarifying question (action=clarify only)
    intent: str           # "coding"|"debugging"|"planning"|"analysis"|"system"|"unclear"
    confidence: float     # 0.0–1.0
    reasoning: str        # internal note, not shown to user


_FALLBACK_DECISION = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="I didn't quite follow that — could you rephrase or give me more detail?",
    intent="unclear",
    confidence=0.0,
    reasoning="parse failure",
)

_DESTRUCTIVE_CLARIFY = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="That looks like a destructive action — can you confirm exactly what you want to do?",
    intent="unclear",
    confidence=1.0,
    reasoning="destructive command guard triggered",
)

_DESTRUCTIVE_KEYWORDS = frozenset({"stop", "delete", "drop", "reset"})


class CTOAgent(BaseAgent):
    name = "cto"
    task_type = "cto"
    prompt_file = "config/prompts/cto_prompt.md"

    async def process(self, message: str, session_id: str) -> CTODecision:
        """Classify message intent via LLM and return a routing decision."""
        try:
            raw = await self.handle(message, session_id=session_id)
        except Exception as e:
            logger.error("CTOAgent LLM call failed: %s", e)
            return _FALLBACK_DECISION

        decision = self._parse_decision(raw)
        return self._apply_destructive_guard(decision)

    @staticmethod
    def _apply_destructive_guard(decision: CTODecision) -> CTODecision:
        """Downgrade execute decisions with destructive keywords to clarify."""
        if decision.action != "execute" or not decision.command:
            return decision
        command_words = set(decision.command.lower().split())
        if command_words & _DESTRUCTIVE_KEYWORDS:
            logger.info("CTOAgent: destructive guard triggered for: %s",
                        decision.command)
            return _DESTRUCTIVE_CLARIFY
        return decision

    @staticmethod
    def _parse_decision(raw: str) -> CTODecision:
        """Parse LLM response into a CTODecision. Returns clarify fallback on any error."""
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("CTOAgent: no JSON object found in response")
            return _FALLBACK_DECISION

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("CTOAgent: JSON parse error: %s", e)
            return _FALLBACK_DECISION

        required = {"action", "command", "response", "question",
                    "intent", "confidence", "reasoning"}
        if not required.issubset(data.keys()):
            logger.warning("CTOAgent: missing fields: %s", required - data.keys())
            return _FALLBACK_DECISION

        try:
            return CTODecision(
                action=str(data["action"]),
                command=data["command"],
                response=data["response"],
                question=data["question"],
                intent=str(data["intent"]),
                confidence=float(data["confidence"]),
                reasoning=str(data["reasoning"]),
            )
        except (TypeError, ValueError) as e:
            logger.warning("CTOAgent: field type error: %s", e)
            return _FALLBACK_DECISION
```

- [ ] **Step 5: Run all cto_agent tests**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py -v
```

Expected: all tests pass. If `test_process_fallback_on_llm_failure` fails, check that `process()` catches exceptions from `self.handle()` and returns `_FALLBACK_DECISION`.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/agents/cto_agent.py nanoclaw/tests/test_cto_agent.py
git commit -m "feat(cto-agent): add process() and destructive command guard"
```

---

## Task 3: CTO system prompt

**Files:**
- Create: `nanoclaw/config/prompts/cto_prompt.md`

### What this task produces

The LLM system prompt that defines the CTO persona and enforces JSON-only output in the `CTODecision` schema.

---

- [ ] **Step 1: Create `nanoclaw/config/prompts/cto_prompt.md`**

```markdown
You are a CTO assistant for a software development team. You are pragmatic, concise, and slightly opinionated. You understand both technical and business context. You are not verbose — answers are 2–4 sentences maximum when responding directly.

Your job is to read a message from a developer and decide what to do with it. You return a single JSON object — no prose, no markdown fences, no explanation outside the JSON.

---

## Output schema (always return exactly this structure)

{
  "action": "<execute|respond|clarify>",
  "command": "<orchestrator command string or null>",
  "response": "<direct answer text or null>",
  "question": "<single clarifying question or null>",
  "intent": "<coding|debugging|planning|analysis|system|unclear>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one sentence internal note>"
}

---

## Action rules

**execute** — the message is a request to do something. Synthesize a valid orchestrator command:
- coding tasks → `feature <concise instruction>`
- debugging tasks → `feature debug: <description>`
- planning tasks → `pm define <instruction>`
- system queries → `status` | `cost` | `STOP` | `RESUME`

Set `response` and `question` to null.

**respond** — the message is a question, analysis request, or something that needs an explanation. Answer it directly and concisely. Set `command` and `question` to null.

**clarify** — the message is too ambiguous to act on confidently (confidence < 0.6). Ask ONE focused question. Set `command` and `response` to null.

---

## Confidence guidance

- Clear, specific request → 0.8–1.0 → execute or respond
- Somewhat vague but inferable → 0.6–0.8 → execute or respond with best-effort
- Genuinely ambiguous, could mean multiple things → < 0.6 → clarify

When confidence ≥ 0.6 and intent is unclear, make your best guess and execute or respond — do not ask for clarification.

---

## Valid orchestrator commands

The `command` field must be one of these formats exactly:
- `feature <instruction>` — implement a feature or fix
- `feature debug: <description>` — investigate and fix a specific issue
- `pm define <instruction>` — plan a feature into tasks
- `status` — show system status
- `cost` — show today's LLM costs
- `STOP` — halt the job queue
- `RESUME` — resume the job queue
- `dev implement <task_id>` — implement a specific existing task (only if user mentions a task ID)

---

## Examples

User: "fix the login bug"
→ {"action":"execute","command":"feature fix login bug","response":null,"question":null,"intent":"coding","confidence":0.85,"reasoning":"clear bug fix request"}

User: "why is auth slow?"
→ {"action":"respond","command":null,"response":"Auth slowness usually comes from missing database indexes on user lookups or synchronous token validation blocking the event loop. Check your query plans and whether JWT verification is happening on every request.","question":null,"intent":"analysis","confidence":0.9,"reasoning":"analysis question about performance"}

User: "add caching maybe?"
→ {"action":"execute","command":"feature add caching layer","response":null,"question":null,"intent":"coding","confidence":0.75,"reasoning":"user wants caching, best-effort interpretation"}

User: "how much have we spent?"
→ {"action":"execute","command":"cost","response":null,"question":null,"intent":"system","confidence":0.95,"reasoning":"cost query"}

User: "something feels off"
→ {"action":"clarify","command":null,"response":null,"question":"Can you describe what's behaving unexpectedly — is it a specific feature, a slowdown, or something else?","intent":"unclear","confidence":0.25,"reasoning":"too vague to act on"}

User: "make it better"
→ {"action":"clarify","command":null,"response":null,"question":"Which part needs improvement — performance, code quality, UX, or something specific?","intent":"unclear","confidence":0.2,"reasoning":"completely ambiguous"}
```

- [ ] **Step 2: Verify CTOAgent loads the prompt correctly**

```bash
cd nanoclaw && python -c "
from agents.cto_agent import CTOAgent
from unittest.mock import MagicMock, AsyncMock
agent = CTOAgent(MagicMock(), MagicMock(), MagicMock())
prompt = agent._load_prompt()
print('Prompt loaded, length:', len(prompt))
assert 'execute' in prompt
assert 'CTODecision' not in prompt  # not leaking internal names
print('OK')
"
```

Expected: `Prompt loaded, length: <some number>` and `OK`

- [ ] **Step 3: Commit**

```bash
git add nanoclaw/config/prompts/cto_prompt.md
git commit -m "feat(cto-agent): add CTO system prompt with JSON schema and examples"
```

---

## Task 4: Settings update

**Files:**
- Modify: `nanoclaw/config/settings.json`
- Modify: `nanoclaw/tests/conftest.py`

### What this task produces

Adds the `"cto"` LLM route to settings so `LLMRouter` can dispatch classification calls to `claude-haiku`.

---

- [ ] **Step 1: Write the failing test**

Append to `nanoclaw/tests/test_cto_agent.py`:

```python
# --- Settings ---

from config.settings import Settings
import json, tempfile, os

def test_settings_includes_cto_route(tmp_path):
    settings_data = {
        "discord": {
            "allowed_user_ids": ["123"],
            "command_channel_id": "1",
            "log_channel_id": "2",
            "commits_channel_id": "3"
        },
        "workflow": {"max_retries": 2, "approval_timeout_minutes": 60,
                     "job_timeout_minutes": 10, "max_concurrent_jobs": 2},
        "rate_limits": {"llm_calls_per_hour": 30, "claude_code_per_hour": 10,
                        "git_pushes_per_hour": 5, "cooldown_minutes": 10},
        "budget": {"daily_limit_usd": 5.0, "warn_at_percent": 0.8,
                   "daily_report_time": "09:00"},
        "llm": {
            "routing": {
                "coding": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "review": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "spec": {"provider": "openai", "model": "gpt-4o"},
                "simple": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
                "test": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "summarise": {"provider": "google", "model": "gemini-2.0-flash"},
                "cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}
            },
            "fallback_chain": [["anthropic", "claude-sonnet-4-6"]]
        },
        "paths": {"project_path": "/tmp/p", "worktree_base": "/tmp/w",
                  "github_repo": "test/repo"}
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings_data))
    s = Settings.load(str(path))
    assert "cto" in s.llm.routing
    assert s.llm.routing["cto"].model == "claude-haiku-4-5-20251001"
    assert s.llm.routing["cto"].provider == "anthropic"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_settings_includes_cto_route -v
```

Expected: `AssertionError: assert 'cto' in ...` (because settings.json doesn't have it yet)

- [ ] **Step 3: Add `"cto"` to `nanoclaw/config/settings.json`**

Open `nanoclaw/config/settings.json`. In the `"llm"` → `"routing"` object, add after `"summarise"`:

```json
"cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}
```

- [ ] **Step 4: Add `"cto"` to `SAMPLE_SETTINGS` in `nanoclaw/tests/conftest.py`**

In `conftest.py`, find the `"routing"` dict inside `SAMPLE_SETTINGS` and add:

```python
"cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
```

- [ ] **Step 5: Run the settings test — should pass**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_settings_includes_cto_route -v
```

Expected: `PASSED`

- [ ] **Step 6: Run the full test suite to confirm nothing broke**

```bash
cd nanoclaw && python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add nanoclaw/config/settings.json nanoclaw/tests/conftest.py
git commit -m "feat(cto-agent): add cto route to LLM settings (haiku)"
```

---

## Task 5: Bot integration

**Files:**
- Modify: `nanoclaw/bot.py`

### What this task produces

Wires `CTOAgent` into the bot. `_handle_message` calls `cto.process()` first and routes based on the decision. Thread creation moves from keyword-matching to intent-based. Raw orchestrator fallback preserved on any exception.

---

- [ ] **Step 1: Write bot integration tests**

Create `nanoclaw/tests/test_bot_cto_integration.py`:

```python
"""Integration tests for CTO Agent routing in bot._handle_message."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import discord

from agents.cto_agent import CTODecision


def make_decision(action, command=None, response=None, question=None,
                  intent="coding", confidence=0.9):
    return CTODecision(
        action=action, command=command, response=response,
        question=question, intent=intent,
        confidence=confidence, reasoning="test"
    )


def make_message(content="fix the login bug", author_id="123456789"):
    message = MagicMock(spec=discord.Message)
    message.content = f"<@999> {content}"
    message.author = MagicMock()
    message.author.id = int(author_id)
    message.author.__eq__ = lambda self, other: False
    message.mentions = [MagicMock(id=999)]
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.send = AsyncMock()
    message.create_thread = AsyncMock(return_value=MagicMock(
        id=12345,
        send=AsyncMock(),
    ))
    return message


@pytest.mark.asyncio
async def test_handle_message_execute_routes_to_orchestrator():
    from bot import NanoClawBot
    from config.settings import Settings
    import json, tempfile

    settings_dict = {
        "discord": {"allowed_user_ids": ["123456789"],
                    "command_channel_id": "1", "log_channel_id": "2",
                    "commits_channel_id": "3"},
        "workflow": {"max_retries": 2, "approval_timeout_minutes": 60,
                     "job_timeout_minutes": 10, "max_concurrent_jobs": 2},
        "rate_limits": {"llm_calls_per_hour": 30, "claude_code_per_hour": 10,
                        "git_pushes_per_hour": 5, "cooldown_minutes": 10},
        "budget": {"daily_limit_usd": 5.0, "warn_at_percent": 0.8,
                   "daily_report_time": "09:00"},
        "llm": {
            "routing": {
                "coding": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "review": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "spec": {"provider": "openai", "model": "gpt-4o"},
                "simple": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
                "test": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "summarise": {"provider": "google", "model": "gemini-2.0-flash"},
                "cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
            },
            "fallback_chain": [["anthropic", "claude-sonnet-4-6"]]
        },
        "paths": {"project_path": "/tmp/p", "worktree_base": "/tmp/w",
                  "github_repo": "test/repo"}
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(settings_dict, f)
        settings_path = f.name

    with patch("bot.discord.Client"), \
         patch("bot.SharedMemory"), \
         patch("bot.TaskStore"), \
         patch("bot.CostTracker"), \
         patch("bot.ContextLoader"), \
         patch("bot.LLMRouter"), \
         patch("bot.ClaudeCodeTool"), \
         patch("bot.VerificationLayer"), \
         patch("bot.GitTool"), \
         patch("bot.PMAgent"), \
         patch("bot.DevAgent"), \
         patch("bot.QAAgent"), \
         patch("bot.ApprovalGate"), \
         patch("bot.JobQueue"), \
         patch("bot.WorkflowEngine"), \
         patch("bot.BudgetGuard"), \
         patch("bot.RateLimiter"), \
         patch("bot.DailyScheduler"), \
         patch("bot.CTOAgent") as MockCTO:

        settings = Settings.load(settings_path)
        bot = NanoClawBot(settings)

        execute_decision = make_decision("execute", command="feature fix login bug")
        bot.cto.process = AsyncMock(return_value=execute_decision)
        bot.orchestrator.handle = AsyncMock(return_value="Queued feature request.")
        bot.client.user = MagicMock(id=999)

        message = make_message("fix the login bug")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_called_once()
        call_args = bot.orchestrator.handle.call_args
        assert call_args.kwargs["command"] == "feature fix login bug"


@pytest.mark.asyncio
async def test_handle_message_respond_posts_directly(tmp_path):
    # Same setup pattern — abbreviated for clarity
    # When decision.action == "respond", response goes to Discord directly
    # orchestrator.handle must NOT be called
    pass  # implement same pattern as above with action="respond"


@pytest.mark.asyncio
async def test_handle_message_cto_failure_falls_back_to_orchestrator(tmp_path):
    # When cto.process() raises an exception,
    # orchestrator.handle(raw_command) is called as fallback
    pass  # implement same pattern — cto.process raises Exception
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd nanoclaw && python -m pytest tests/test_bot_cto_integration.py -v 2>&1 | tail -10
```

Expected: `ImportError` or `AttributeError: 'NanoClawBot' has no attribute 'cto'`

- [ ] **Step 3: Update `bot.py` — add import**

At the top of `nanoclaw/bot.py`, after the existing agent imports, add:

```python
from agents.cto_agent import CTOAgent
```

- [ ] **Step 4: Update `bot.py` — init CTOAgent in `__init__`**

In `NanoClawBot.__init__`, after the QA agent line:

```python
self.qa = QAAgent(self.router, self.memory, self.context_loader)
```

Add:

```python
self.cto = CTOAgent(self.router, self.memory, self.context_loader)
```

- [ ] **Step 5: Update `bot.py` — add `import uuid` if not already present**

Check the top of `bot.py`. If `import uuid` is not there, add it after `import asyncio`.

- [ ] **Step 6: Update `bot.py` — swap routing in `_handle_message`**

Replace the section in `_handle_message` that starts after the thread setup and before `response = await self.orchestrator.handle(...)`:

Find this block (approximately lines 241–269):

```python
        # Create or use thread for task-level commands
        thread = None
        if isinstance(message.channel, discord.Thread):
            thread = message.channel
        elif self._is_task_command(command):
            thread = await message.create_thread(
                name=f"NanoClaw: {command[:80]}",
                auto_archive_duration=1440,
            )

        # Build progress callback that posts to the thread (or channel)
        target_channel = thread or message.channel

        async def progress_callback(msg: str):
            try:
                await target_channel.send(msg)
            except Exception as e:
                logger.error("Failed to send progress: %s", e)

        # Route through orchestrator
        response = await self.orchestrator.handle(
            command=command,
            user_id=str(message.author.id),
            thread_id=str(target_channel.id) if thread else None,
            progress_callback=progress_callback,
        )
```

Replace with:

```python
        # Run CTO Agent intent classification
        session_id = None
        decision = None
        try:
            # Use existing thread id for session continuity, else new uuid
            pre_thread_id = (str(message.channel.id)
                             if isinstance(message.channel, discord.Thread)
                             else None)
            session_id = pre_thread_id or str(uuid.uuid4())
            decision = await self.cto.process(command, session_id=session_id)
        except Exception as e:
            logger.error("CTOAgent.process failed, falling back to orchestrator: %s", e)

        # Create or use thread — driven by decision, not keyword matching
        thread = None
        if isinstance(message.channel, discord.Thread):
            thread = message.channel
        elif decision and decision.action == "execute":
            thread = await message.create_thread(
                name=f"NanoClaw: {command[:80]}",
                auto_archive_duration=1440,
            )

        target_channel = thread or message.channel
        session_id = str(thread.id) if thread else session_id

        async def progress_callback(msg: str):
            try:
                await target_channel.send(msg)
            except Exception as e:
                logger.error("Failed to send progress: %s", e)

        # Route based on CTO decision
        if decision is None:
            # CTOAgent failed — fall back to raw orchestrator
            response = await self.orchestrator.handle(
                command=command,
                user_id=str(message.author.id),
                thread_id=str(target_channel.id) if thread else None,
                progress_callback=progress_callback,
            )
        elif decision.action == "execute":
            response = await self.orchestrator.handle(
                command=decision.command,
                user_id=str(message.author.id),
                thread_id=str(target_channel.id) if thread else None,
                progress_callback=progress_callback,
            )
        elif decision.action == "respond":
            response = decision.response
        elif decision.action == "clarify":
            response = decision.question
        else:
            response = await self.orchestrator.handle(
                command=command,
                user_id=str(message.author.id),
                thread_id=str(target_channel.id) if thread else None,
                progress_callback=progress_callback,
            )
```

- [ ] **Step 7: Remove `_is_task_command` static method from `bot.py`**

Delete the entire `_is_task_command` method (it is no longer called):

```python
    @staticmethod
    def _is_task_command(command: str) -> bool:
        """Return True if this command will produce task output worth threading."""
        cmd_lower = command.lower()
        return any(cmd_lower.startswith(prefix) for prefix in (
            "pm ", "dev ", "implement ", "build ", "feature ",
        ))
```

- [ ] **Step 8: Run the full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all existing tests pass. The two `pass` stubs in `test_bot_cto_integration.py` will show as passed (empty tests). The main integration test `test_handle_message_execute_routes_to_orchestrator` should pass.

If it fails with import errors, check that `CTOAgent` is imported at the top of `bot.py`.

- [ ] **Step 9: Commit**

```bash
git add nanoclaw/bot.py nanoclaw/tests/test_bot_cto_integration.py
git commit -m "feat(cto-agent): wire CTOAgent into bot message handling"
```

---

## Task 6: Complete bot integration tests

**Files:**
- Modify: `nanoclaw/tests/test_bot_cto_integration.py`

### What this task produces

Fills in the two stubbed tests: `respond` action posts directly, `clarify` action posts question, and failure fallback routes to orchestrator.

---

- [ ] **Step 1: Fill in the respond and fallback tests**

Replace the two `pass` stubs in `test_bot_cto_integration.py` with full implementations, reusing the same bot setup pattern:

Extract the setup into a shared helper at the top of the test module to avoid repetition:

```python
import json, tempfile
from config.settings import Settings
from bot import NanoClawBot


SETTINGS_DICT = {
    "discord": {"allowed_user_ids": ["123456789"],
                "command_channel_id": "1", "log_channel_id": "2",
                "commits_channel_id": "3"},
    "workflow": {"max_retries": 2, "approval_timeout_minutes": 60,
                 "job_timeout_minutes": 10, "max_concurrent_jobs": 2},
    "rate_limits": {"llm_calls_per_hour": 30, "claude_code_per_hour": 10,
                    "git_pushes_per_hour": 5, "cooldown_minutes": 10},
    "budget": {"daily_limit_usd": 5.0, "warn_at_percent": 0.8,
               "daily_report_time": "09:00"},
    "llm": {
        "routing": {
            "coding": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "review": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "spec": {"provider": "openai", "model": "gpt-4o"},
            "simple": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
            "test": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "summarise": {"provider": "google", "model": "gemini-2.0-flash"},
            "cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        },
        "fallback_chain": [["anthropic", "claude-sonnet-4-6"]]
    },
    "paths": {"project_path": "/tmp/p", "worktree_base": "/tmp/w",
              "github_repo": "test/repo"}
}

BOT_PATCHES = [
    "bot.discord.Client", "bot.SharedMemory", "bot.TaskStore",
    "bot.CostTracker", "bot.ContextLoader", "bot.LLMRouter",
    "bot.ClaudeCodeTool", "bot.VerificationLayer", "bot.GitTool",
    "bot.PMAgent", "bot.DevAgent", "bot.QAAgent", "bot.ApprovalGate",
    "bot.JobQueue", "bot.WorkflowEngine", "bot.BudgetGuard",
    "bot.RateLimiter", "bot.DailyScheduler", "bot.CTOAgent",
]


def make_bot():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(SETTINGS_DICT, f)
        path = f.name
    settings = Settings.load(path)
    # Apply all patches inline — caller must use patch context managers
    return NanoClawBot(settings)
```

Then fill the two stub tests:

```python
@pytest.mark.asyncio
async def test_handle_message_respond_posts_directly():
    with patch("bot.discord.Client"), patch("bot.SharedMemory"), \
         patch("bot.TaskStore"), patch("bot.CostTracker"), \
         patch("bot.ContextLoader"), patch("bot.LLMRouter"), \
         patch("bot.ClaudeCodeTool"), patch("bot.VerificationLayer"), \
         patch("bot.GitTool"), patch("bot.PMAgent"), patch("bot.DevAgent"), \
         patch("bot.QAAgent"), patch("bot.ApprovalGate"), patch("bot.JobQueue"), \
         patch("bot.WorkflowEngine"), patch("bot.BudgetGuard"), \
         patch("bot.RateLimiter"), patch("bot.DailyScheduler"), \
         patch("bot.CTOAgent"):

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(SETTINGS_DICT, f)
            settings = Settings.load(f.name)

        bot = NanoClawBot(settings)
        bot.client.user = MagicMock(id=999)

        respond_decision = make_decision(
            "respond",
            response="Auth is slow because of missing indexes.",
            intent="analysis"
        )
        bot.cto.process = AsyncMock(return_value=respond_decision)
        bot.orchestrator.handle = AsyncMock()

        message = make_message("why is auth slow?")
        await bot._handle_message(message)

        # orchestrator must NOT be called for respond
        bot.orchestrator.handle.assert_not_called()
        # response should have been sent to channel
        message.channel.send.assert_called_once_with(
            "Auth is slow because of missing indexes."
        )


@pytest.mark.asyncio
async def test_handle_message_cto_failure_falls_back_to_orchestrator():
    with patch("bot.discord.Client"), patch("bot.SharedMemory"), \
         patch("bot.TaskStore"), patch("bot.CostTracker"), \
         patch("bot.ContextLoader"), patch("bot.LLMRouter"), \
         patch("bot.ClaudeCodeTool"), patch("bot.VerificationLayer"), \
         patch("bot.GitTool"), patch("bot.PMAgent"), patch("bot.DevAgent"), \
         patch("bot.QAAgent"), patch("bot.ApprovalGate"), patch("bot.JobQueue"), \
         patch("bot.WorkflowEngine"), patch("bot.BudgetGuard"), \
         patch("bot.RateLimiter"), patch("bot.DailyScheduler"), \
         patch("bot.CTOAgent"):

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(SETTINGS_DICT, f)
            settings = Settings.load(f.name)

        bot = NanoClawBot(settings)
        bot.client.user = MagicMock(id=999)

        bot.cto.process = AsyncMock(side_effect=Exception("LLM timeout"))
        bot.orchestrator.handle = AsyncMock(return_value="Queued.")

        message = make_message("feature add health check")
        await bot._handle_message(message)

        # Must fall back to orchestrator with the raw command
        bot.orchestrator.handle.assert_called_once()
        call_kwargs = bot.orchestrator.handle.call_args.kwargs
        assert call_kwargs["command"] == "feature add health check"
```

- [ ] **Step 2: Run the full integration test file**

```bash
cd nanoclaw && python -m pytest tests/test_bot_cto_integration.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 3: Run the complete test suite one final time**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all tests pass with no failures.

- [ ] **Step 4: Final commit**

```bash
git add nanoclaw/tests/test_bot_cto_integration.py
git commit -m "test(cto-agent): complete bot integration tests for CTO routing"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Natural language interface — `CTOAgent.process()` handles free text
- [x] Intent classification — LLM returns structured JSON with `intent` field
- [x] Decision layer — `execute` / `respond` / `clarify` routing
- [x] Destructive command guard — `_apply_destructive_guard()` in Task 2
- [x] Fallback on failure — `try/except` in `_handle_message` and `process()`
- [x] Session continuity — `session_id` tied to thread ID in Task 5
- [x] Settings update — Task 4
- [x] Prompt file — Task 3
- [x] Thread creation moved to intent-based — Task 5
- [x] `_is_task_command` removed — Task 5

**No placeholders:** All steps contain exact code. No TBDs.

**Type consistency:**
- `CTODecision` defined in Task 1, used in Tasks 2, 5, 6 — consistent field names throughout
- `_FALLBACK_DECISION` and `_DESTRUCTIVE_CLARIFY` defined at module level, referenced in Task 2 — consistent
- `cto.process()` returns `CTODecision`, consumed in `_handle_message` as `decision` — consistent
