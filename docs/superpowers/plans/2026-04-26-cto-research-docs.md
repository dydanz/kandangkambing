# CTO Research & Documentation Capability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `document` action to CTOAgent that triggers a deep Sonnet LLM pass, posts a structured markdown document to Discord, and optionally commits it to `docs/research/` in the repo.

**Architecture:** CTOAgent's classification prompt gains a `document` action; when classified, `process()` calls the new `research()` method (Sonnet, `task_type="research"`) to generate the content; bot.py's `_handle_message` posts a Discord preview and optionally calls `GitTool.write_and_commit()`. Existing `execute`/`respond`/`clarify` paths are untouched.

**Tech Stack:** Python 3.11, pytest-asyncio (strict), GitPython, discord.py, existing `LLMRouter`/`BaseAgent`/`GitTool` patterns.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/conftest.py` | Modify | Add `"research"` to `SAMPLE_SETTINGS` routing |
| `config/settings.json` | Modify | Add `"research"` LLM route |
| `config/settings.docker.json` | Modify | Add `"research"` LLM route |
| `agents/cto_agent.py` | Modify | New fields on `CTODecision`; `research()` method; updated `process()` and `_parse_decision()` |
| `config/prompts/cto_prompt.md` | Modify | Add `document` action rules + example |
| `config/prompts/cto_research_prompt.md` | Create | Deep research/doc-generation system prompt |
| `tools/git_tool.py` | Modify | Add `write_and_commit()` method |
| `bot.py` | Modify | Add `_format_doc_preview()` helper; handle `decision.action == "document"` |
| `tests/test_cto_agent.py` | Modify | Tests for document parsing, `research()`, `process()` doc path |
| `tests/test_bot_cto_integration.py` | Modify | Tests for bot document routing + git save |

---

## Task 1: Settings — add `research` LLM route

**Files:**
- Modify: `tests/conftest.py`
- Modify: `config/settings.json`
- Modify: `config/settings.docker.json`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cto_agent.py`, after the existing `# --- Shared mock helpers` section:

```python
def test_settings_has_research_route(settings_path):
    from config.settings import Settings
    s = Settings.load(settings_path)
    # SAMPLE_SETTINGS must have a "research" routing entry
    assert "research" in s.llm.routing
    assert s.llm.routing["research"].model == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_settings_has_research_route -v
```

Expected: `FAILED — KeyError` or `AssertionError` (key absent from routing).

- [ ] **Step 3: Add `research` route to conftest SAMPLE_SETTINGS**

In `tests/conftest.py`, add one line inside `"routing"`:

```python
"llm": {
    "routing": {
        "coding":    {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "review":    {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "spec":      {"provider": "openai",    "model": "gpt-4o"},
        "simple":    {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "test":      {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "summarise": {"provider": "google",    "model": "gemini-2.0-flash"},
        "cto":       {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "research":  {"provider": "anthropic", "model": "claude-sonnet-4-6"},   # ← add
    },
    ...
```

- [ ] **Step 4: Add `research` route to both settings files**

In `config/settings.json`, add inside `"routing"`:
```json
"research":  {"provider": "anthropic", "model": "claude-sonnet-4-6"}
```

In `config/settings.docker.json`, add inside `"routing"`:
```json
"research":  {"provider": "anthropic", "model": "claude-sonnet-4-6"}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_settings_has_research_route -v
```

Expected: `PASSED`.

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add nanoclaw/tests/conftest.py nanoclaw/config/settings.json nanoclaw/config/settings.docker.json
git commit -m "feat(cto): add research LLM route (Sonnet) to settings"
```

---

## Task 2: CTODecision new fields + updated `_parse_decision`

**Files:**
- Modify: `nanoclaw/agents/cto_agent.py` (lines 1–6, 12–19, 91–113)
- Modify: `nanoclaw/tests/test_cto_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cto_agent.py`:

```python
# --- document action parsing ---

def test_parse_decision_document_action():
    raw = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "technical brief requested",
        "doc_title": "OAuth 2.0 Options — Technical Brief",
        "doc_filename": "oauth-2-options.md",
        "save_to_repo": True,
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "document"
    assert decision.doc_title == "OAuth 2.0 Options — Technical Brief"
    assert decision.doc_filename == "oauth-2-options.md"
    assert decision.save_to_repo is True
    assert decision.document_content is None


def test_parse_decision_document_missing_doc_fields_returns_clarify():
    # document action without doc_title/doc_filename is invalid → clarify fallback
    raw = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "missing doc fields",
        # doc_title and doc_filename intentionally absent
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_parse_decision_document_action tests/test_cto_agent.py::test_parse_decision_document_missing_doc_fields_returns_clarify -v
```

Expected: both `FAILED` (action "document" not in `valid_actions`, CTODecision lacks new fields).

- [ ] **Step 3: Update `agents/cto_agent.py` — add import + new fields**

Replace the top of the file (imports + CTODecision definition):

```python
"""CTOAgent — natural language interface layer for NanoClaw."""
import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from agents.base import BaseAgent

logger = logging.getLogger("nanoclaw.agents.cto")


@dataclass(frozen=True)
class CTODecision:
    action: str           # "execute" | "respond" | "clarify" | "document"
    command: str | None   # orchestrator command string (action=execute only)
    response: str | None  # direct answer (action=respond only)
    question: str | None  # one clarifying question (action=clarify only)
    intent: str           # "coding"|"debugging"|"planning"|"analysis"|"system"|"research"|"unclear"
    confidence: float     # 0.0–1.0
    reasoning: str        # internal note, not shown to user
    # document-action fields (None/False for all other actions)
    doc_title: str | None = None
    doc_filename: str | None = None
    save_to_repo: bool = False
    document_content: str | None = None
```

- [ ] **Step 4: Update `_parse_decision` to handle the `document` action**

Replace the `_parse_decision` staticmethod body (lines 74–114 in current file):

```python
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

        valid_actions = {"execute", "respond", "clarify", "document"}
        if data.get("action") not in valid_actions:
            logger.warning("CTOAgent: unknown action '%s'", data.get("action"))
            return _FALLBACK_DECISION

        if data.get("action") == "document":
            if not data.get("doc_title") or not data.get("doc_filename"):
                logger.warning("CTOAgent: document action missing doc_title/doc_filename")
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
                doc_title=data.get("doc_title"),
                doc_filename=data.get("doc_filename"),
                save_to_repo=bool(data.get("save_to_repo", False)),
                document_content=None,
            )
        except (TypeError, ValueError) as e:
            logger.warning("CTOAgent: field type error: %s", e)
            return _FALLBACK_DECISION
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_parse_decision_document_action tests/test_cto_agent.py::test_parse_decision_document_missing_doc_fields_returns_clarify -v
```

Expected: both `PASSED`.

- [ ] **Step 6: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all tests pass (existing tests still use the same field names; new default fields don't affect them since `CTODecision` construction in tests uses keyword args and existing fields remain unchanged).

- [ ] **Step 7: Commit**

```bash
git add nanoclaw/agents/cto_agent.py nanoclaw/tests/test_cto_agent.py
git commit -m "feat(cto): add document action fields to CTODecision + parse support"
```

---

## Task 3: Prompts — add `document` action + create research prompt

**Files:**
- Modify: `nanoclaw/config/prompts/cto_prompt.md`
- Create: `nanoclaw/config/prompts/cto_research_prompt.md`

These are prompt files, not tested via unit tests. Verify by reading the loaded prompt in a smoke check step.

- [ ] **Step 1: Update `config/prompts/cto_prompt.md`**

Change the output schema section to include the new fields:

```
## Output schema (always return exactly this structure)

{
  "action": "<execute|respond|clarify|document>",
  "command": "<orchestrator command string or null>",
  "response": "<direct answer text or null>",
  "question": "<single clarifying question or null>",
  "intent": "<coding|debugging|planning|analysis|system|research|unclear>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one sentence internal note>",
  "doc_title": "<descriptive document title or null>",
  "doc_filename": "<kebab-case filename with .md extension or null>",
  "save_to_repo": <true|false>
}
```

Add the `document` action rule after the `clarify` rule:

```
**document** — the message requests research, a technical brief, architecture notes, or any multi-section written output. Set:
  - doc_title: descriptive title (e.g. "OAuth 2.0 Options — Technical Brief")
  - doc_filename: kebab-case filename with .md extension (e.g. "oauth-2-options.md")
  - save_to_repo: true if user says "save", "commit", "write to repo", or "for the team"
  - command, response, question: null
```

Add example at the end of the Examples section:

```
User: "research OAuth options and write a brief for PMO"
→ {"action":"document","command":null,"response":null,"question":null,"intent":"research","confidence":0.9,"reasoning":"technical brief requested","doc_title":"OAuth 2.0 Options — Technical Brief","doc_filename":"oauth-2-options.md","save_to_repo":true}

User: "document the current architecture of the auth module"
→ {"action":"document","command":null,"response":null,"question":null,"intent":"research","confidence":0.85,"reasoning":"architecture documentation requested","doc_title":"Auth Module Architecture","doc_filename":"auth-module-architecture.md","save_to_repo":false}
```

Also add `doc_title`, `doc_filename`, `save_to_repo` as null in all existing examples that don't use them:

Actually, to keep existing examples clean, add a note at the top of Examples section:

```
Note: For non-document actions, omit doc_title/doc_filename/save_to_repo or set to null/false.
```

- [ ] **Step 2: Create `config/prompts/cto_research_prompt.md`**

```markdown
You are a technical research assistant for a software development team. Your job is to produce a well-structured, practical markdown document based on a research topic and document title.

## Output format

Always produce a complete markdown document with exactly these sections. Replace placeholder text with real, specific content — no vague filler.

```
# {doc_title}

## Summary
One paragraph executive summary. What is this document about and what is the key takeaway?

## Context
Why this topic matters for the team. What prompted this research? What problem does it solve?

## Options / Findings
Structured findings, options, or analysis. Use `### Option N: Title` subsections.
For each option include: what it is, when to use it, pros, cons.

## Recommendation
A clear, specific recommendation with rationale. "Use X because Y." No hedging.

## Risks & Trade-offs
Bullet list of the key risks or trade-offs the team should be aware of.

## References
Relevant links, RFCs, standards, or internal patterns to review.
```

## Style rules

- Be specific and opinionated. Vague answers waste the reader's time.
- Use concrete examples (code snippets, config, command-line) where helpful.
- Write for a senior engineer who wants signal, not textbook definitions.
- Keep each section focused: Summary ≤ 150 words, each Option ≤ 200 words.
- Do not add sections beyond those listed above.
```

- [ ] **Step 3: Verify prompts load correctly**

```bash
cd nanoclaw && python -c "
from pathlib import Path
p1 = Path('config/prompts/cto_prompt.md').read_text()
p2 = Path('config/prompts/cto_research_prompt.md').read_text()
assert 'document' in p1, 'document action missing from cto_prompt.md'
assert 'doc_title' in p1, 'doc_title missing from cto_prompt.md'
assert 'save_to_repo' in p1, 'save_to_repo missing from cto_prompt.md'
assert 'Options / Findings' in p2, 'Options section missing from research prompt'
print('Prompts OK')
"
```

Expected: `Prompts OK`

- [ ] **Step 4: Commit**

```bash
git add nanoclaw/config/prompts/cto_prompt.md nanoclaw/config/prompts/cto_research_prompt.md
git commit -m "feat(cto): add document action to classification prompt + research prompt"
```

---

## Task 4: CTOAgent.research() method

**Files:**
- Modify: `nanoclaw/agents/cto_agent.py`
- Modify: `nanoclaw/tests/test_cto_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cto_agent.py`:

```python
# --- research() method ---

@pytest.mark.asyncio
async def test_research_returns_markdown_string():
    markdown_doc = "# OAuth 2.0 Options\n\n## Summary\nThree flows are relevant..."
    agent = make_cto_agent(markdown_doc)
    # Override router to return markdown for task_type="research"
    from tools.providers.base import LLMResponse
    agent.router.route = AsyncMock(return_value=LLMResponse(
        content=markdown_doc,
        model="claude-sonnet-4-6",
        provider="anthropic",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.001,
    ))
    result = await agent.research(
        topic="research OAuth options",
        doc_title="OAuth 2.0 Options — Technical Brief",
        session_id="s1",
    )
    assert result == markdown_doc
    # Verify it called router with task_type="research"
    call_kwargs = agent.router.route.call_args.kwargs
    assert call_kwargs["task_type"] == "research"


@pytest.mark.asyncio
async def test_research_saves_to_memory():
    markdown_doc = "# Test Doc\n\n## Summary\nContent here."
    agent = make_cto_agent(markdown_doc)
    from tools.providers.base import LLMResponse
    agent.router.route = AsyncMock(return_value=LLMResponse(
        content=markdown_doc,
        model="claude-sonnet-4-6",
        provider="anthropic",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.001,
    ))
    await agent.research("document auth architecture", "Auth Architecture", "s1")
    agent.memory.save_message.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_research_returns_markdown_string tests/test_cto_agent.py::test_research_saves_to_memory -v
```

Expected: both `FAILED` (`CTOAgent` has no `research` attribute).

- [ ] **Step 3: Implement `CTOAgent.research()`**

Add the method to `CTOAgent` in `agents/cto_agent.py`, after the `process()` method:

```python
    async def research(self, topic: str, doc_title: str, session_id: str) -> str:
        """Deep Sonnet LLM pass — generates a structured markdown research document."""
        research_prompt_path = Path("config/prompts/cto_research_prompt.md")
        if research_prompt_path.exists():
            system = research_prompt_path.read_text().strip()
        else:
            system = "You are a technical researcher. Generate structured markdown documents."

        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Document title: {doc_title}\n\n"
                    "Produce the full research document now."
                ),
            },
        ]

        response = await self.router.route(
            task_type="research",
            messages=messages,
            session_id=session_id,
            agent=self.name,
        )

        await self.memory.save_message(
            role=self.name,
            agent=self.name,
            content=response.content,
            task_id=None,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )
        return response.content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_research_returns_markdown_string tests/test_cto_agent.py::test_research_saves_to_memory -v
```

Expected: both `PASSED`.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/agents/cto_agent.py nanoclaw/tests/test_cto_agent.py
git commit -m "feat(cto): add research() method — deep Sonnet LLM pass for doc generation"
```

---

## Task 5: CTOAgent.process() — call research() when action is document

**Files:**
- Modify: `nanoclaw/agents/cto_agent.py` (process method)
- Modify: `nanoclaw/tests/test_cto_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cto_agent.py`:

```python
# --- process() document path ---

@pytest.mark.asyncio
async def test_process_document_calls_research_and_populates_content():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "brief requested",
        "doc_title": "OAuth 2.0 Options — Technical Brief",
        "doc_filename": "oauth-2-options.md",
        "save_to_repo": True,
    })
    agent = make_cto_agent(doc_json)
    markdown_doc = "# OAuth 2.0 Options\n\n## Summary\nThree flows..."

    # First router call → classification (returns doc_json)
    # Second router call → research (returns markdown_doc)
    from tools.providers.base import LLMResponse
    agent.router.route = AsyncMock(side_effect=[
        LLMResponse(content=doc_json, model="claude-haiku-4-5-20251001",
                    provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001),
        LLMResponse(content=markdown_doc, model="claude-sonnet-4-6",
                    provider="anthropic", tokens_in=100, tokens_out=200, cost_usd=0.001),
    ])

    decision = await agent.process("research OAuth options for PMO", session_id="s1")

    assert decision.action == "document"
    assert decision.document_content == markdown_doc
    assert decision.doc_title == "OAuth 2.0 Options — Technical Brief"
    assert decision.save_to_repo is True


@pytest.mark.asyncio
async def test_process_document_research_failure_returns_clarify():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "brief requested",
        "doc_title": "OAuth 2.0 Options",
        "doc_filename": "oauth.md",
        "save_to_repo": False,
    })
    agent = make_cto_agent(doc_json)
    from tools.providers.base import LLMResponse

    classify_response = LLMResponse(
        content=doc_json, model="claude-haiku-4-5-20251001",
        provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001,
    )
    agent.router.route = AsyncMock(side_effect=[
        classify_response,
        Exception("Sonnet unavailable"),
    ])

    decision = await agent.process("document auth module", session_id="s1")

    assert decision.action == "clarify"
    assert "couldn't generate" in decision.question.lower()


@pytest.mark.asyncio
async def test_process_document_save_to_repo_false():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.85,
        "reasoning": "architecture doc",
        "doc_title": "Auth Module Architecture",
        "doc_filename": "auth-architecture.md",
        "save_to_repo": False,
    })
    agent = make_cto_agent(doc_json)
    from tools.providers.base import LLMResponse
    agent.router.route = AsyncMock(side_effect=[
        LLMResponse(content=doc_json, model="claude-haiku-4-5-20251001",
                    provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001),
        LLMResponse(content="# Auth Architecture\n\n## Summary\n...",
                    model="claude-sonnet-4-6", provider="anthropic",
                    tokens_in=100, tokens_out=200, cost_usd=0.001),
    ])

    decision = await agent.process("document auth module architecture", session_id="s1")

    assert decision.action == "document"
    assert decision.save_to_repo is False
    assert decision.document_content is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_process_document_calls_research_and_populates_content tests/test_cto_agent.py::test_process_document_research_failure_returns_clarify tests/test_cto_agent.py::test_process_document_save_to_repo_false -v
```

Expected: all `FAILED` (process() doesn't call research() yet).

- [ ] **Step 3: Update `CTOAgent.process()` to call `research()` for document action**

Replace the current `process()` method in `agents/cto_agent.py`:

```python
    async def process(self, message: str, session_id: str) -> CTODecision:
        """Classify message intent via LLM and return a routing decision."""
        try:
            raw = await self.handle(message, session_id=session_id)
        except Exception as e:
            logger.error("CTOAgent LLM call failed: %s", e)
            return _FALLBACK_DECISION

        decision = self._parse_decision(raw)
        decision = self._apply_destructive_guard(decision)

        if decision.action == "document":
            try:
                content = await self.research(
                    topic=message,
                    doc_title=decision.doc_title or "Research Document",
                    session_id=session_id,
                )
                decision = dataclasses.replace(decision, document_content=content)
            except Exception as e:
                logger.error("CTOAgent.research() failed: %s", e)
                return dataclasses.replace(
                    _FALLBACK_DECISION,
                    question="I couldn't generate the document — try again?",
                )

        return decision
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_cto_agent.py::test_process_document_calls_research_and_populates_content tests/test_cto_agent.py::test_process_document_research_failure_returns_clarify tests/test_cto_agent.py::test_process_document_save_to_repo_false -v
```

Expected: all `PASSED`.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/agents/cto_agent.py nanoclaw/tests/test_cto_agent.py
git commit -m "feat(cto): process() calls research() for document action, populates document_content"
```

---

## Task 6: GitTool.write_and_commit()

**Files:**
- Modify: `nanoclaw/tools/git_tool.py`
- Create: `nanoclaw/tests/test_git_tool_write_commit.py`

- [ ] **Step 1: Write the failing tests**

Create `nanoclaw/tests/test_git_tool_write_commit.py`:

```python
"""Tests for GitTool.write_and_commit()."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal real git repo in a temp directory."""
    import subprocess
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    # Initial commit so HEAD exists
    (repo_dir / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    return repo_dir


@pytest.mark.asyncio
async def test_write_and_commit_creates_file(fake_repo, tmp_path):
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/oauth.md",
        content="# OAuth\n\n## Summary\nTest content.",
        message="docs(cto): add oauth research doc",
    )

    written = fake_repo / "docs" / "research" / "oauth.md"
    assert written.exists()
    assert "OAuth" in written.read_text()


@pytest.mark.asyncio
async def test_write_and_commit_makes_a_commit(fake_repo, tmp_path):
    import subprocess
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/notes.md",
        content="# Notes",
        message="docs(cto): add notes",
    )

    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(fake_repo), capture_output=True, text=True,
    )
    assert "docs(cto): add notes" in result.stdout


@pytest.mark.asyncio
async def test_write_and_commit_creates_parent_dirs(fake_repo, tmp_path):
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/deep/nested/file.md",
        content="# Deep",
        message="test nested dirs",
    )

    assert (fake_repo / "docs" / "research" / "deep" / "nested" / "file.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_git_tool_write_commit.py -v
```

Expected: all `FAILED` (`GitTool` has no `write_and_commit` attribute).

- [ ] **Step 3: Implement `GitTool.write_and_commit()`**

Add the method to `tools/git_tool.py`, before the existing `run()` method:

```python
    async def write_and_commit(self, path: str, content: str, message: str) -> None:
        """Write content to path in project_path, stage, and commit.

        Writes directly to the main repo (not a worktree) — research docs are
        reference material committed to main, not feature branches.
        Raises GitError if the commit fails.
        """
        full_path = Path(self.repo.working_dir) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        self.repo.git.add(path)
        self.repo.index.commit(message)
        logger.info("Committed research doc: %s", path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_git_tool_write_commit.py -v
```

Expected: all `PASSED`.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/tools/git_tool.py nanoclaw/tests/test_git_tool_write_commit.py
git commit -m "feat(git): add write_and_commit() for research docs"
```

---

## Task 7: bot.py — handle document action + integration tests

**Files:**
- Modify: `nanoclaw/bot.py`
- Modify: `nanoclaw/tests/test_bot_cto_integration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot_cto_integration.py`:

```python
# --- document action ---

def make_document_decision(
    doc_title="OAuth 2.0 Options",
    doc_filename="oauth-2-options.md",
    save_to_repo=False,
    document_content="# OAuth 2.0 Options\n\n## Summary\nThree flows...",
):
    return CTODecision(
        action="document",
        command=None,
        response=None,
        question=None,
        intent="research",
        confidence=0.9,
        reasoning="brief requested",
        doc_title=doc_title,
        doc_filename=doc_filename,
        save_to_repo=save_to_repo,
        document_content=document_content,
    )


@pytest.mark.asyncio
async def test_handle_message_document_posts_preview():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=False)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()

        message = make_message("research OAuth options")
        await bot._handle_message(message)

        # Orchestrator must NOT be called
        bot.orchestrator.handle.assert_not_called()
        # Channel must receive the document preview
        message.channel.send.assert_called_once()
        sent_text = message.channel.send.call_args[0][0]
        assert "OAuth" in sent_text
        # No thread created (document action doesn't create a thread)
        message.create_thread.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_document_save_to_repo_calls_git():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=True)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()
        bot.git.write_and_commit = AsyncMock()

        message = make_message("research OAuth options and save it")
        await bot._handle_message(message)

        # git.write_and_commit called with correct path
        bot.git.write_and_commit.assert_called_once()
        call_kwargs = bot.git.write_and_commit.call_args.kwargs
        assert call_kwargs["path"] == "docs/research/oauth-2-options.md"
        assert "OAuth" in call_kwargs["content"]
        assert "oauth" in call_kwargs["message"].lower()

        # Two sends: preview + "Saved to..." confirmation
        assert message.channel.send.call_count == 2
        second_send = message.channel.send.call_args_list[1][0][0]
        assert "docs/research/oauth-2-options.md" in second_send


@pytest.mark.asyncio
async def test_handle_message_document_git_failure_posts_warning():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=True)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()
        bot.git.write_and_commit = AsyncMock(side_effect=Exception("git commit failed"))

        message = make_message("research OAuth options and commit it")
        await bot._handle_message(message)

        # Document preview still sent
        assert message.channel.send.call_count == 2
        warning_msg = message.channel.send.call_args_list[1][0][0]
        assert "⚠️" in warning_msg
        assert "repo" in warning_msg.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_bot_cto_integration.py::test_handle_message_document_posts_preview tests/test_bot_cto_integration.py::test_handle_message_document_save_to_repo_calls_git tests/test_bot_cto_integration.py::test_handle_message_document_git_failure_posts_warning -v
```

Expected: all `FAILED` (bot doesn't handle `decision.action == "document"` yet).

- [ ] **Step 3: Add `_format_doc_preview()` module-level function to `bot.py`**

Add after the imports and before the `NanoClawBot` class:

```python
def _format_doc_preview(content: str) -> str:
    """Format document content for Discord (max ~1900 chars)."""
    if len(content) <= 1900:
        return content
    truncated = content[:1900]
    return truncated + (
        "\n\n…Document truncated. "
        "Ask me to save it to the repo for the full version."
    )
```

- [ ] **Step 4: Add `document` branch in `_handle_message()`**

In `bot.py`, inside `_handle_message`, add the document case after the existing `elif decision.action == "clarify":` branch and before the final `else:`:

```python
        elif decision.action == "document":
            discord_preview = _format_doc_preview(decision.document_content or "")
            await target_channel.send(discord_preview)
            if decision.save_to_repo and decision.doc_filename:
                path = f"docs/research/{decision.doc_filename}"
                try:
                    await self.git.write_and_commit(
                        path=path,
                        content=decision.document_content or "",
                        message=f"docs(cto): add research doc — {decision.doc_title}",
                    )
                    await target_channel.send(f"📄 Saved to `{path}`")
                except Exception as e:
                    logger.error("git.write_and_commit failed: %s", e)
                    await target_channel.send("⚠️ Could not save to repo")
            response = None
```

The `response` variable is set to `None` here because the sends are already done inside the branch. At the end of `_handle_message`, the existing `if response:` check will skip the final send.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_bot_cto_integration.py::test_handle_message_document_posts_preview tests/test_bot_cto_integration.py::test_handle_message_document_save_to_repo_calls_git tests/test_bot_cto_integration.py::test_handle_message_document_git_failure_posts_warning -v
```

Expected: all `PASSED`.

- [ ] **Step 6: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add nanoclaw/bot.py nanoclaw/tests/test_bot_cto_integration.py
git commit -m "feat(bot): handle document action — Discord preview + optional git commit"
```

---

## Verification

After all tasks complete, run the full suite one final time:

```bash
cd nanoclaw && python -m pytest tests/ -v --ignore=tests/test_discord_tokens.py
```

Expected: all tests pass with no errors or warnings about missing fixtures.

To verify the document flow end-to-end in Discord, mention the CTO bot:
```
@CTO research JWT vs session tokens and write a brief for the PM
@CTO document the current auth module architecture and save it to the repo
```
