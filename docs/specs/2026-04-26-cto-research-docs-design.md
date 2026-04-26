---
title: CTO Research & Documentation Capability
date: 2026-04-26
status: approved
---

# CTO Research & Documentation Design

## Problem

The current `CTOAgent` handles `analysis` intent by returning a 2-4 sentence
inline answer (`action="respond"`). This is sufficient for quick questions
("why is auth slow?") but not for deeper requests like:

- "Research OAuth 2.0 options and write a technical brief for PM"
- "Document the current architecture of the auth module for SED"
- "Write a spike report on caching strategies and save it to the repo"

These require a structured multi-section document, a deeper LLM pass, and
optionally a git-committed file that PM/SED/QAD can reference.

---

## Goal

Add a `document` action to `CTOAgent` that:

1. Triggers a deeper LLM pass (Sonnet, not Haiku) to produce a structured
   markdown document.
2. Posts the document as a formatted message in the Discord thread (Option B).
3. Optionally commits the document to `docs/research/` in the repo (Option C).
4. Short inline answers via `action="respond"` remain unchanged (Option A).

---

## Prerequisite

This spec depends on **`2026-04-26-multi-bot-registry-design.md`** being
implemented first. The `document` response is posted by the CTO Discord client.

---

## Architecture

```
User mentions @CTO with a research/doc request
    ↓
CTOAgent.process()  — Haiku classifies intent
    ↓  action="document"
CTOAgent.research() — Sonnet generates structured doc
    ↓
CTODecision (document)
    ↓
bot._handle_message()
    ├─ cto_client.send(formatted discord message)    ← Option B
    └─ if save_to_repo: GitTool.write_and_commit()   ← Option C
    └─ cto_client.send("📄 Saved to docs/research/oauth-flows.md")
```

### What changes

| File | Change |
|------|--------|
| `agents/cto_agent.py` | Add `document` action + fields to `CTODecision`; add `research()` method |
| `config/prompts/cto_prompt.md` | Add `document` action rules + examples |
| `config/prompts/cto_research_prompt.md` | **New** — deep research/doc generation prompt |
| `config/settings.json` | Add `"research"` route → Sonnet |
| `config/settings.docker.json` | Add `"research"` route → Sonnet |
| `tests/conftest.py` | Add `"research"` to `SAMPLE_SETTINGS` routing |
| `bot.py` | Handle `decision.action == "document"` |
| `tests/test_cto_agent.py` | Add tests for `document` action and `research()` |

### What does NOT change

`BotRegistry`, `Orchestrator`, `WorkflowEngine`, `PMAgent`, `DevAgent`, `QAAgent`,
`CodeReviewerAgent` — untouched.

---

## CTODecision — New Fields

```python
@dataclass(frozen=True)
class CTODecision:
    action: str           # "execute" | "respond" | "clarify" | "document"
    command: str | None
    response: str | None
    question: str | None
    intent: str           # adds "research" to existing values
    confidence: float
    reasoning: str
    # document-action only
    doc_title: str | None       # e.g. "OAuth 2.0 Options — Technical Brief"
    doc_filename: str | None    # e.g. "oauth-2-options.md"
    save_to_repo: bool          # whether to commit to docs/research/
```

`doc_title`, `doc_filename`, `save_to_repo` are `None` / `False` for all
non-document actions — no impact on existing code paths.

---

## CTOAgent — New Methods

### Classification prompt change (`cto_prompt.md`)

Add `document` as a valid action with rules:

```
**document** — the message requests research, a technical brief, architecture
notes, or any multi-section written output. Set:
  - doc_title: descriptive title for the document
  - doc_filename: kebab-case filename with .md extension
  - save_to_repo: true if user says "save", "commit", "write to repo", "for the team"
  - command, response, question: null
```

Add example:
```
User: "research OAuth options and write a brief for PMO"
→ {"action":"document","command":null,"response":null,"question":null,
   "intent":"research","confidence":0.9,"reasoning":"technical brief requested",
   "doc_title":"OAuth 2.0 Options — Technical Brief",
   "doc_filename":"oauth-2-options.md","save_to_repo":true}
```

### `research()` method (new)

```python
async def research(
    self,
    topic: str,
    doc_title: str,
    session_id: str,
) -> str:
    """
    Deep LLM pass using Sonnet to generate a structured markdown document.
    Returns raw markdown string.
    task_type="research" routes to claude-sonnet-4-6.
    """
```

The research prompt (`cto_research_prompt.md`) instructs the LLM to produce:

```markdown
# {doc_title}

## Summary
One paragraph executive summary.

## Context
Why this matters / what prompted this research.

## Options / Findings
Structured findings, options, or analysis. Use subsections as needed.

## Recommendation
Clear recommendation with rationale.

## Risks & Trade-offs
Key risks or trade-offs to consider.

## References
Any relevant links, RFCs, or internal docs.
```

### `process()` change

```python
async def process(self, message: str, session_id: str) -> CTODecision:
    # Existing: Haiku classifies → returns decision
    # New: if decision.action == "document", call research() to populate
    #      a document_content field on the decision
    ...
    if decision.action == "document":
        content = await self.research(message, decision.doc_title, session_id)
        # Return a new CTODecision with document_content populated
        decision = CTODecision(**{**vars(decision), "document_content": content})
    return self._apply_destructive_guard(decision)
```

`document_content` is added as a non-frozen field populated after classification.
Since `CTODecision` is `frozen=True`, `process()` constructs a new instance with
`dataclasses.replace(decision, document_content=content)`.

---

## Bot Handling (`bot.py`)

```python
elif decision.action == "document":
    # Format for Discord (truncate to 1900 chars if needed; full doc in file)
    discord_preview = _format_doc_preview(decision.document_content)
    await target_channel.send(discord_preview)

    if decision.save_to_repo:
        path = f"docs/research/{decision.doc_filename}"
        await self.git.write_and_commit(
            path=path,
            content=decision.document_content,
            message=f"docs(cto): add research doc — {decision.doc_title}",
        )
        await target_channel.send(
            f"📄 Saved to `{path}`"
        )
```

`_format_doc_preview(content)` wraps the markdown in a Discord code block if
under 1900 chars, otherwise posts the first 1900 chars with a "… (full doc saved
to repo)" note.

---

## GitTool — New Method

```python
async def write_and_commit(self, path: str, content: str, message: str) -> None:
    """
    Write content to path (relative to project_path), stage, and commit.
    Creates parent directories if needed.
    Raises GitError if the commit fails.
    """
```

This method writes directly to `project_path` (not a worktree) since research
docs are not feature branches — they're reference material committed to main.

---

## Settings Changes

Add `"research"` route to both `settings.json` and `settings.docker.json`:

```json
"research": {"provider": "anthropic", "model": "claude-sonnet-4-6"}
```

Add to `SAMPLE_SETTINGS` in `tests/conftest.py`:
```python
"research": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
```

---

## Discord Message Examples

**Short analysis (unchanged — `action="respond"`):**
```
[CTO]  Auth is slow because of N+1 queries on user lookup.
       Add an index on users.email.
```

**Research document (`action="document"`, no save):**
```
[CTO]  📋 OAuth 2.0 Options — Technical Brief
       ─────────────────────────────────────
       ## Summary
       Three OAuth 2.0 flows are relevant: Authorization Code (recommended),
       Client Credentials (service-to-service), and Device Flow (CLI tools)...
       [full doc in message]
```

**Research document with repo save (`save_to_repo=true`):**
```
[CTO]  📋 OAuth 2.0 Options — Technical Brief
       [formatted document]
[CTO]  📄 Saved to `docs/research/oauth-2-options.md`
```

---

## Testing

### `tests/test_cto_agent.py` (additions)

```python
test_parse_decision_document_action()
    # valid JSON with action="document" parses correctly
    # doc_title, doc_filename, save_to_repo populated

test_process_document_calls_research()
    # when classify returns document, research() is called
    # returned CTODecision has document_content set

test_process_document_save_to_repo_false()
    # save_to_repo=false → no git call expected downstream

test_research_returns_markdown_string()
    # mocked Sonnet router → returns markdown, save_message called
```

### `tests/test_bot_cto_integration.py` (additions)

```python
test_handle_message_document_posts_preview()
    # decision.action="document" → channel.send called with preview
    # orchestrator.handle NOT called

test_handle_message_document_save_to_repo_calls_git()
    # save_to_repo=True → git.write_and_commit called with correct path
```

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| `research()` LLM call fails | Caught in `process()`; returns `clarify` fallback with "I couldn't generate the document — try again?" |
| `git.write_and_commit()` fails | Logged as ERROR; document still posted to Discord; message updated to "⚠️ Could not save to repo" |
| Document > 1900 chars and no repo save | First 1900 chars posted; note appended: "Document truncated. Ask me to save it to the repo for the full version." |

---

## Out of Scope

- Document versioning or overwrite detection in the repo
- CTO document search / retrieval ("find the brief I wrote last week")
- PM/SED/QAD reading docs programmatically — they reference by filename in Discord
- Multi-bot registry changes — covered in `2026-04-26-multi-bot-registry-design.md`
