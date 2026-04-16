# Design: CodeReviewerAgent

**Date:** 2026-04-16
**Status:** Approved
**Author:** Dandi + Claude

---

## Overview

Add a `CodeReviewerAgent` to NanoClaw that performs automated AI code review on GitHub PRs. The reviewer runs as a pipeline step after QA passes and the PR is created, posts findings to both GitHub and Discord, and gates human approval based on finding severity. A manual Discord command enables on-demand review of any PR in the configured repo.

---

## Problem Statement

The current NanoClaw pipeline (PM → Dev → QA → ApprovalGate → PR) has no code quality review step. QAAgent validates functional acceptance criteria only. The existing `/review-code` slash command is an inline Claude Code command with no agent identity, no GitHub integration, and no pipeline trigger. Engineers must review AI-generated PRs manually with no structured AI assistance.

---

## New Pipeline Flow

**Before:**
```
dev.implement() → qa.handle() → approval_gate.request() → dev.commit_and_push()
```

**After:**
```
dev.implement()
  → qa.handle()                              # functional check (unchanged)
  → dev.commit_and_push()                    # PR created early → returns PRInfo(url, number)
  → code_reviewer.review(pr_number)          # gh pr diff → LLM → gh pr review comment
  → if 🔴 Critical findings:
      post Discord warning
      wait_for_github_merge(pr_number)        # only GitHub can resolve
  → else:
      approval_gate.request()                 # Discord ✅/❌ OR GitHub merge (first wins)
```

---

## New Files

### `nanoclaw/agents/code_reviewer.py`

Subclasses `BaseAgent`. Injected with `GitTool`.

```python
class CodeReviewerAgent(BaseAgent):
    name = "code_reviewer"
    task_type = "review"
    prompt_file = "config/prompts/code_reviewer_prompt.md"

    def __init__(self, router, memory, context, git: GitTool):
        super().__init__(router, memory, context)
        self.git = git

    async def review(self, pr_number: int, task_id: str = None,
                     session_id: str = None) -> ReviewResult:
        ...
```

**Internal flow of `review()`:**
1. `diff = self.git.get_pr_diff(pr_number)` — raw unified diff string
2. Build LLM instruction with diff + review checklist
3. `router.route(task_type="review", ...)` — LLM returns structured JSON
4. Parse JSON into `ReviewResult` (same fallback-parse pattern as QAAgent)
5. `self.git.post_pr_review(pr_number, formatted_markdown)` — post GitHub review comment
6. Return `ReviewResult` to caller

**Data types:**

```python
@dataclass
class Finding:
    location: str   # "path/to/file.py:45"
    issue: str
    fix: str

@dataclass
class ReviewResult:
    pr_number: int
    critical: list[Finding]       # 🔴 must fix before merge
    important: list[Finding]      # 🟡 should fix
    suggestions: list[Finding]    # 🔵 nice to have
    positives: list[str]
    summary: str
    github_comment_posted: bool

    @property
    def has_critical(self) -> bool:
        return len(self.critical) > 0
```

**LLM output format (structured JSON):**
```json
{
  "critical":    [{"location": "file.py:12", "issue": "...", "fix": "..."}],
  "important":   [{"location": "file.py:34", "issue": "...", "fix": "..."}],
  "suggestions": [{"location": "file.py:56", "issue": "...", "fix": "..."}],
  "positives":   ["Error handling correct", "..."],
  "summary":     "One paragraph overall assessment"
}
```

---

### `nanoclaw/config/prompts/code_reviewer_prompt.md`

System prompt for `CodeReviewerAgent`. Instructs the LLM to:
- Review for: correctness, security, performance, maintainability, tests, project patterns
- Reference every finding with exact `file:line`
- Explain WHY each issue is a problem
- Provide a specific fix, not just "fix this"
- Return output as valid JSON matching the schema above

Review dimensions:
- **Correctness:** logic errors, edge cases, nil/zero handling, error propagation, data races, resource cleanup
- **Security:** SQL injection, command injection, auth enforcement, sensitive data in logs/responses, input validation
- **Performance:** N+1 queries, unbounded memory growth, unnecessary allocations in hot paths
- **Maintainability:** single responsibility, naming consistency, no duplication of existing logic, no dead code
- **Tests:** new logic has tests, error/edge cases covered, test names describe behavior
- **Project patterns:** error handling conventions, logging patterns, architectural layer boundaries

---

### `.claude/agents/code-reviewer.md`

Agent spec for Claude Code workflows. Documents the reviewer's role, input/output format, and integration points. Replaces the gap left by `/review-code` being an inline command with no agent identity.

---

## Modified Files

### `nanoclaw/tools/git_tool.py`

Three new methods:

**`get_pr_diff(pr_number: int) -> str`**
- Shells out: `gh pr diff <pr_number> --repo <github_repo>`
- Returns raw unified diff as string
- Raises `RuntimeError` on non-zero exit

**`get_pr_state(pr_number: int) -> str`**
- Shells out: `gh pr view <pr_number> --repo <github_repo> --json state --jq '.state'`
- Returns `"OPEN"` | `"MERGED"` | `"CLOSED"`
- Used by `ApprovalGate` polling loop

**`post_pr_review(pr_number: int, body: str) -> None`**
- Shells out: `gh pr review <pr_number> --repo <github_repo> --comment --body <body>`
- Posts formatted markdown review as a GitHub PR comment

---

### `nanoclaw/agents/dev.py`

**`commit_and_push()` return type change:**

```python
# Before
async def commit_and_push(...) -> str:  # returns pr_url
    ...
    return pr_url

# After
PRInfo = namedtuple("PRInfo", ["url", "number"])

async def commit_and_push(...) -> PRInfo:
    ...
    pr_url = await self.git.create_pr(...)
    pr_number = int(pr_url.rstrip("/").rsplit("/", 1)[-1])
    return PRInfo(url=pr_url, number=pr_number)
```

`pr_number` extracted from URL — no extra `gh` call needed.

---

### `nanoclaw/workflow/engine.py`

**`__init__` change:** Add `code_reviewer: CodeReviewerAgent` parameter.

**`_run_task()` restructure** — after QA passes:

```python
# Create PR first
await self._progress(f"{task['id']} QA passed — creating PR...")
pr_info = await self.dev.commit_and_push(task, dev_result)

# Run code review
await self._progress(f"PR created: {pr_info.url} — running code review...")
review = await self.code_reviewer.review(
    pr_number=pr_info.number,
    task_id=task["id"],
    session_id=session_id,
)

# Gate on severity
if review.has_critical:
    await self._progress(
        f"🔴 Critical issues found on PR #{pr_info.number}. "
        f"Fix them and merge on GitHub, or use `review override {pr_info.number}`.\n\n"
        + self._format_review_discord(review)
    )
    merged = await self.gate.wait_for_github_merge(pr_info.number)
    success = merged
else:
    await self._progress(
        f"✅ Code review complete. Awaiting your approval.\n\n"
        + self._format_review_discord(review)
    )
    approved = await self.gate.request(task, dev_result, pr_info=pr_info)
    success = approved

return {"task_id": task["id"], "success": success, "pr_url": pr_info.url}
```

**`_format_review_discord(review: ReviewResult) -> str`:** Formats critical + important findings only (suggestions omitted) into a concise Discord-friendly markdown block.

---

### `nanoclaw/workflow/approval_gate.py`

**New constructor arg:** `git: GitTool` — for PR state polling.

**`request()` updated:** Runs two concurrent awaitables via `asyncio.wait(return_when=FIRST_COMPLETED)`:
1. Discord `asyncio.Event` (existing mechanism — reaction handler calls `resolve()`)
2. `wait_for_github_merge(pr_info.number)` (new — polls GitHub every 30s)

Whichever resolves first cancels the other. Existing `timeout_minutes` applies to the whole gate.

**New method `wait_for_github_merge(pr_number: int, poll_interval_seconds: int = 30) -> bool`:**
```python
async def wait_for_github_merge(self, pr_number, poll_interval_seconds=30) -> bool:
    while True:
        state = self.git.get_pr_state(pr_number)
        if state == "MERGED":
            return True
        if state == "CLOSED":
            return False
        await asyncio.sleep(poll_interval_seconds)
```

**New method `resolve_by_pr(pr_number: int, approved: bool) -> None`:** Used by `review override` command — finds the pending gate keyed by PR number and resolves it.

Internal pending gate storage updated to track `pr_number` alongside `task_id`.

---

### `nanoclaw/orchestrator.py`

**Two new commands:**

**`review <pr_number>`**
- Validates `pr_number` is an integer
- Runs safety gates (budget + rate limit)
- Enqueues job: `code_reviewer.review(pr_number)` → posts result to Discord + GitHub
- Works on any PR in the configured repo
- `review` added to safety-gated keyword set

**`review override <pr_number>`**
- Calls `approval_gate.resolve_by_pr(pr_number, approved=True)`
- Posts Discord confirmation of override
- No effect if no pending gate exists for that PR number

**Routing:**
```python
if keyword == "review":
    if len(parts) >= 2 and parts[1].lower() == "override":
        pr_number = int(parts[2]) if len(parts) >= 3 else None
        return await self._handle_review_override(pr_number)
    pr_number = int(parts[1]) if len(parts) >= 2 else None
    return await self._handle_review(pr_number, thread_id, progress_callback)
```

**`_usage()` updated:**
```
`review <pr_number>`          — AI code review on any PR
`review override <pr_number>` — Force-approve a PR blocked by critical findings
```

**Constructor:** Add `code_reviewer: CodeReviewerAgent` parameter.

---

### `nanoclaw/bot.py`

**New import and instantiation:**
```python
from agents.code_reviewer import CodeReviewerAgent

self.code_reviewer = CodeReviewerAgent(
    self.router, self.memory, self.context_loader, self.git
)
```

**Updated `ApprovalGate` instantiation** (add `git`):
```python
self.approval_gate = ApprovalGate(
    self.client,
    git=self.git,
    timeout_minutes=settings.workflow.approval_timeout_minutes,
)
```

**Updated `WorkflowEngine` instantiation** (add `code_reviewer`):
```python
self.engine = WorkflowEngine(
    pm=self.pm, dev=self.dev, qa=self.qa,
    code_reviewer=self.code_reviewer,
    task_store=self.task_store,
    approval_gate=self.approval_gate,
    max_retries=settings.workflow.max_retries,
)
```

**Updated `Orchestrator` instantiation** (add `code_reviewer`):
```python
self.orchestrator = Orchestrator(
    engine=self.engine,
    task_store=self.task_store,
    job_queue=self.job_queue,
    cost_tracker=self.cost_tracker,
    code_reviewer=self.code_reviewer,
    rate_limiter=self.rate_limiter,
    budget_guard=self.budget_guard,
)
```

---

## Discord Command Reference

| Command | Description |
|---|---|
| `@NanoClaw review <pr_number>` | AI code review on any PR in the repo |
| `@NanoClaw review override <pr_number>` | Force-approve a PR blocked by critical findings |

---

## Approval Gate Behaviour Summary

| Scenario | Discord | GitHub | Result |
|---|---|---|---|
| No critical findings | ✅ reaction | — | Approved |
| No critical findings | ❌ reaction | — | Rejected |
| No critical findings | — | Merged | Approved |
| No critical findings | — | Closed | Rejected |
| Critical findings | `review override` | — | Approved |
| Critical findings | — | Merged | Approved |
| Critical findings | — | Closed | Rejected |
| Any | Timeout | Timeout | Rejected |

---

## What Is NOT in Scope

- GitHub webhook integration (polling is sufficient)
- Auto-fix suggestions applied by the bot
- Review comments on specific diff lines (PR-level comment only)
- Configurable review dimensions per task type
- Review history / audit trail beyond shared memory
