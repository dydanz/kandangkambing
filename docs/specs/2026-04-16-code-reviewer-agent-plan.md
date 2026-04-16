# CodeReviewerAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CodeReviewerAgent` to NanoClaw that automatically reviews GitHub PRs after QA passes, posts findings to GitHub and Discord, and gates human approval on finding severity.

**Architecture:** `CodeReviewerAgent` subclasses `BaseAgent` and is injected with `GitTool`. The pipeline is restructured so `commit_and_push` runs before the approval gate, producing a PR that the reviewer fetches via `gh pr diff`. The `ApprovalGate` is upgraded to a dual-signal gate (Discord reaction OR GitHub merge polling). A new `review` Discord command enables on-demand review of any PR.

**Tech Stack:** Python 3.11+, asyncio, `gh` CLI (already used), `unittest.mock` + `pytest-asyncio` for tests.

**Spec:** `docs/specs/2026-04-16-code-reviewer-agent-design.md`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `nanoclaw/agents/dev.py` | Add `PRInfo` namedtuple; update `commit_and_push` return type |
| Modify | `nanoclaw/tools/git_tool.py` | Add `get_pr_diff`, `get_pr_state`, `post_pr_review` |
| Create | `nanoclaw/agents/code_reviewer.py` | `Finding`, `ReviewResult`, `CodeReviewerAgent` |
| Create | `nanoclaw/config/prompts/code_reviewer_prompt.md` | LLM system prompt |
| Modify | `nanoclaw/workflow/approval_gate.py` | Dual-signal gate + `wait_for_github_merge` + `resolve_by_pr` |
| Modify | `nanoclaw/workflow/engine.py` | Restructure `_run_task`; add `code_reviewer` |
| Modify | `nanoclaw/orchestrator.py` | Add `review` + `review override` commands |
| Modify | `nanoclaw/bot.py` | Wire `CodeReviewerAgent`; update constructor calls |
| Create | `.claude/agents/code-reviewer.md` | Agent spec for Claude Code workflows |
| Modify | `nanoclaw/tests/test_agents.py` | Tests for `CodeReviewerAgent` |
| Modify | `nanoclaw/tests/test_tools.py` | Tests for new `GitTool` methods |
| Modify | `nanoclaw/tests/test_workflow_engine.py` | Update engine + gate + orchestrator tests |

---

## Task 1: Add `PRInfo` to `dev.py`

`commit_and_push` currently returns `str` (pr_url). The engine needs both the URL and the PR number. We'll return a `PRInfo` namedtuple instead, extracting the number from the URL.

**Files:**
- Modify: `nanoclaw/agents/dev.py`
- Modify: `nanoclaw/tests/test_agents.py`

- [ ] **Step 1: Write the failing test**

Add to `nanoclaw/tests/test_agents.py`:

```python
from agents.dev import DevAgent, DevResult, PRInfo

@pytest.mark.asyncio
async def test_dev_commit_and_push_returns_prinfo():
    """commit_and_push should return PRInfo(url, number)."""
    router = make_router()
    memory = make_memory()
    context = make_context()

    git = MagicMock()
    git.commit = MagicMock(return_value="abc123")
    git.push = MagicMock(return_value="nanoclaw/TASK-001-test")
    git.create_pr = AsyncMock(return_value="https://github.com/owner/repo/pull/42")
    git.remove_worktree = MagicMock()

    task_store = MagicMock()
    task_store.update = AsyncMock()

    agent = DevAgent(router, memory, context, MagicMock(), git, task_store)
    task = {
        "id": "TASK-001", "title": "test", "description": "desc",
        "acceptance_criteria": [],
    }
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="nanoclaw/TASK-001-test", details="done", files_changed=["a.py"],
    )

    pr_info = await agent.commit_and_push(task, dev_result)

    assert isinstance(pr_info, PRInfo)
    assert pr_info.url == "https://github.com/owner/repo/pull/42"
    assert pr_info.number == 42


def test_pr_info_number_extracted_from_url():
    """PRInfo.number is the integer at the end of the GitHub URL."""
    from agents.dev import PRInfo
    info = PRInfo(url="https://github.com/owner/repo/pull/123", number=123)
    assert info.number == 123
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd nanoclaw && python -m pytest tests/test_agents.py::test_dev_commit_and_push_returns_prinfo -v
```

Expected: `FAILED` — `ImportError: cannot import name 'PRInfo' from 'agents.dev'`

- [ ] **Step 3: Add `PRInfo` and update `commit_and_push` in `dev.py`**

Add after the existing imports in `nanoclaw/agents/dev.py`:

```python
from collections import namedtuple

PRInfo = namedtuple("PRInfo", ["url", "number"])
```

Replace the `commit_and_push` method body:

```python
async def commit_and_push(self, task: dict,
                          dev_result: DevResult) -> "PRInfo":
    """
    Called ONLY after WorkflowEngine receives QA pass.
    Returns PRInfo(url, number).
    """
    # Commit
    message = f"feat({task['id']}): {task.get('title', 'implementation')}"
    self.git.commit(dev_result.worktree_path, message)

    # Push
    self.git.push(dev_result.worktree_path)

    # Create PR
    pr_title = f"[NanoClaw] {task['id']}: {task.get('title', '')}"
    pr_body = (
        f"## Task\n{task.get('description', '')}\n\n"
        f"## Acceptance Criteria\n"
        + "\n".join(f"- [ ] {ac}" for ac in task.get("acceptance_criteria", []))
        + f"\n\n## Files Changed\n"
        + "\n".join(f"- `{f}`" for f in dev_result.files_changed)
        + "\n\n---\n*Generated by NanoClaw DevAgent*"
    )
    pr_url = await self.git.create_pr(
        pr_title, pr_body, dev_result.branch,
    )

    # Extract PR number from URL (always ends in /<number>)
    pr_number = int(pr_url.rstrip("/").rsplit("/", 1)[-1])

    # Clean up worktree
    self.git.remove_worktree(dev_result.worktree_path)

    # Update task
    await self.task_store.update(
        task["id"], status="done", pr_url=pr_url,
    )

    return PRInfo(url=pr_url, number=pr_number)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd nanoclaw && python -m pytest tests/test_agents.py::test_dev_commit_and_push_returns_prinfo tests/test_agents.py::test_pr_info_number_extracted_from_url -v
```

Expected: `2 passed`

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all tests pass. Note: `test_run_feature_success` in `test_workflow_engine.py` checks `pr_url` — it will still pass because `engine.py` hasn't changed yet and `mock_dev.commit_and_push` still returns a string. We update that mock in Task 6.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/agents/dev.py nanoclaw/tests/test_agents.py
git commit -m "feat(dev): commit_and_push returns PRInfo(url, number)"
```

---

## Task 2: Add PR methods to `GitTool`

Three new async methods: `get_pr_diff` (fetch unified diff), `get_pr_state` (OPEN/MERGED/CLOSED), and `post_pr_review` (post review comment). All shell out to `gh` CLI, following the same pattern as the existing `create_pr`.

**Files:**
- Modify: `nanoclaw/tools/git_tool.py`
- Modify: `nanoclaw/tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `nanoclaw/tests/test_tools.py`:

```python
# --- GitTool PR methods ---

@pytest.mark.asyncio
async def test_git_tool_get_pr_diff_success():
    """get_pr_diff returns stdout from gh pr diff."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"diff --git a/f.py b/f.py\n+new line", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        result = await git_tool.get_pr_diff(42)

    assert result == "diff --git a/f.py b/f.py\n+new line"
    call_args = mock_exec.call_args[0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "diff" in call_args
    assert "42" in call_args


@pytest.mark.asyncio
async def test_git_tool_get_pr_diff_failure():
    """get_pr_diff raises RuntimeError on non-zero exit."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"not found"))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"

        with pytest.raises(RuntimeError, match="gh pr diff failed"):
            await git_tool.get_pr_diff(99)


@pytest.mark.asyncio
async def test_git_tool_get_pr_state_merged():
    """get_pr_state returns MERGED when gh reports it."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"MERGED\n", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        state = await git_tool.get_pr_state(42)

    assert state == "MERGED"


@pytest.mark.asyncio
async def test_git_tool_get_pr_state_open():
    """get_pr_state returns OPEN for an open PR."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"OPEN\n", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        state = await git_tool.get_pr_state(42)

    assert state == "OPEN"


@pytest.mark.asyncio
async def test_git_tool_post_pr_review_success():
    """post_pr_review calls gh pr review with --comment."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        await git_tool.post_pr_review(42, "## Review\nLooks good!")

    call_args = mock_exec.call_args[0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "review" in call_args
    assert "--comment" in call_args


@pytest.mark.asyncio
async def test_git_tool_post_pr_review_failure():
    """post_pr_review raises RuntimeError on non-zero exit."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"auth error"))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"

        with pytest.raises(RuntimeError, match="gh pr review failed"):
            await git_tool.post_pr_review(42, "body")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_tools.py::test_git_tool_get_pr_diff_success tests/test_tools.py::test_git_tool_get_pr_state_merged tests/test_tools.py::test_git_tool_post_pr_review_success -v
```

Expected: `FAILED` — `AttributeError: 'GitTool' object has no attribute 'get_pr_diff'`

- [ ] **Step 3: Add the three methods to `git_tool.py`**

Add after the `get_changed_files` method (before `async def run`):

```python
async def get_pr_diff(self, pr_number: int) -> str:
    """Fetch unified diff for a GitHub PR. Returns raw diff string."""
    cmd = ["gh", "pr", "diff", str(pr_number)]
    if self.github_repo:
        cmd.extend(["--repo", self.github_repo])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip()
        raise RuntimeError(f"gh pr diff failed: {error}")

    return stdout.decode()

async def get_pr_state(self, pr_number: int) -> str:
    """Return PR state: 'OPEN', 'MERGED', or 'CLOSED'."""
    cmd = [
        "gh", "pr", "view", str(pr_number),
        "--json", "state", "--jq", ".state",
    ]
    if self.github_repo:
        cmd.extend(["--repo", self.github_repo])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip()
        raise RuntimeError(f"gh pr view failed: {error}")

    return stdout.decode().strip()

async def post_pr_review(self, pr_number: int, body: str) -> None:
    """Post a review comment on a GitHub PR."""
    cmd = [
        "gh", "pr", "review", str(pr_number),
        "--comment", "--body", body,
    ]
    if self.github_repo:
        cmd.extend(["--repo", self.github_repo])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip()
        raise RuntimeError(f"gh pr review failed: {error}")
```

- [ ] **Step 4: Run all new GitTool tests**

```bash
cd nanoclaw && python -m pytest tests/test_tools.py -k "pr" -v
```

Expected: `6 passed`

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/tools/git_tool.py nanoclaw/tests/test_tools.py
git commit -m "feat(git_tool): add get_pr_diff, get_pr_state, post_pr_review"
```

---

## Task 3: Create `CodeReviewerAgent`

New agent that fetches a PR diff, asks the LLM to review it, parses structured JSON findings, formats a GitHub comment, and posts it.

**Files:**
- Create: `nanoclaw/agents/code_reviewer.py`
- Modify: `nanoclaw/tests/test_agents.py`

- [ ] **Step 1: Write the failing tests**

Add to `nanoclaw/tests/test_agents.py`:

```python
import json as json_module
from agents.code_reviewer import CodeReviewerAgent, ReviewResult, Finding


def make_git_mock(diff="diff --git a/f.py\n+line"):
    git = MagicMock()
    git.get_pr_diff = AsyncMock(return_value=diff)
    git.post_pr_review = AsyncMock()
    return git


@pytest.mark.asyncio
async def test_code_reviewer_returns_review_result():
    """review() returns a ReviewResult with structured findings."""
    response_json = json_module.dumps({
        "critical": [{"location": "app.py:10", "issue": "SQL injection", "fix": "Use params"}],
        "important": [],
        "suggestions": [],
        "positives": ["Good error handling"],
        "summary": "One critical issue found.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=42, task_id="TASK-001", session_id="s1")

    assert isinstance(result, ReviewResult)
    assert result.pr_number == 42
    assert result.has_critical is True
    assert len(result.critical) == 1
    assert result.critical[0].location == "app.py:10"
    assert result.critical[0].issue == "SQL injection"
    assert result.positives == ["Good error handling"]


@pytest.mark.asyncio
async def test_code_reviewer_posts_github_comment():
    """review() calls post_pr_review with formatted markdown."""
    response_json = json_module.dumps({
        "critical": [],
        "important": [],
        "suggestions": [],
        "positives": ["Clean code"],
        "summary": "No issues.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=7)

    git.post_pr_review.assert_called_once()
    call_args = git.post_pr_review.call_args
    assert call_args[0][0] == 7  # pr_number
    body = call_args[0][1]
    assert "NanoClaw AI Code Review" in body
    assert result.github_comment_posted is True


@pytest.mark.asyncio
async def test_code_reviewer_fallback_on_bad_json():
    """review() returns empty-severity ReviewResult when LLM returns non-JSON."""
    router = make_router("I cannot review this code.")
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=5)

    assert result.pr_number == 5
    assert result.has_critical is False
    assert result.summary == "I cannot review this code."


@pytest.mark.asyncio
async def test_code_reviewer_github_post_failure_doesnt_raise():
    """review() logs warning and continues if post_pr_review fails."""
    response_json = json_module.dumps({
        "critical": [], "important": [], "suggestions": [],
        "positives": [], "summary": "All good.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()
    git.post_pr_review = AsyncMock(side_effect=RuntimeError("gh auth error"))

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=3)

    # Should not raise — just mark comment as not posted
    assert result.github_comment_posted is False


def test_review_result_has_critical_false_when_empty():
    result = ReviewResult(
        pr_number=1, critical=[], important=[], suggestions=[],
        positives=[], summary="", github_comment_posted=False,
    )
    assert result.has_critical is False


def test_review_result_has_critical_true_when_findings():
    finding = Finding(location="a.py:1", issue="bug", fix="fix it")
    result = ReviewResult(
        pr_number=1, critical=[finding], important=[], suggestions=[],
        positives=[], summary="", github_comment_posted=False,
    )
    assert result.has_critical is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_agents.py::test_code_reviewer_returns_review_result -v
```

Expected: `FAILED` — `ImportError: cannot import name 'CodeReviewerAgent'`

- [ ] **Step 3: Create `nanoclaw/agents/code_reviewer.py`**

```python
"""CodeReviewerAgent — AI code review on GitHub PRs."""
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from agents.base import BaseAgent
from tools.git_tool import GitTool

logger = logging.getLogger("nanoclaw.agents.code_reviewer")


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


class CodeReviewerAgent(BaseAgent):
    name = "code_reviewer"
    task_type = "review"
    prompt_file = "config/prompts/code_reviewer_prompt.md"

    def __init__(self, router, memory, context, git: GitTool):
        super().__init__(router, memory, context)
        self.git = git

    async def review(self, pr_number: int,
                     task_id: Optional[str] = None,
                     session_id: Optional[str] = None) -> ReviewResult:
        """
        Fetch PR diff, run LLM review, post GitHub comment.
        Returns ReviewResult with severity-bucketed findings.
        """
        session_id = session_id or str(uuid.uuid4())

        # 1. Fetch diff
        diff = await self.git.get_pr_diff(pr_number)

        # 2. Build instruction
        instruction = self._build_review_instruction(pr_number, diff)

        # 3. LLM call via BaseAgent message building
        history = await self.memory.get_recent(limit=5, task_id=task_id)
        ctx = await self.context.load_all()
        messages = self._build_messages(instruction, history, ctx)

        response = await self.router.route(
            task_type=self.task_type,
            messages=messages,
            session_id=session_id,
            task_id=task_id,
            agent=self.name,
        )

        # 4. Save to memory
        await self.memory.save_message(
            role=self.name, agent=self.name,
            content=response.content, task_id=task_id,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )

        # 5. Parse result
        result = self._parse_review_response(response.content, pr_number)

        # 6. Post GitHub comment (non-fatal if it fails)
        comment = self._format_github_comment(result)
        try:
            await self.git.post_pr_review(pr_number, comment)
            result.github_comment_posted = True
        except RuntimeError as e:
            logger.warning("Failed to post GitHub review comment for PR #%d: %s",
                           pr_number, e)

        return result

    @staticmethod
    def _build_review_instruction(pr_number: int, diff: str) -> str:
        return (
            f"## Code Review Request — PR #{pr_number}\n\n"
            f"Review the following diff for correctness, security, performance, "
            f"maintainability, test coverage, and adherence to project patterns.\n\n"
            f"## Diff\n\n```diff\n{diff}\n```\n\n"
            f"## Instructions\n"
            f"Return ONLY valid JSON in this exact format — no other text:\n"
            f'{{"critical": [{{"location": "file.py:N", "issue": "...", "fix": "..."}}], '
            f'"important": [{{"location": "...", "issue": "...", "fix": "..."}}], '
            f'"suggestions": [{{"location": "...", "issue": "...", "fix": "..."}}], '
            f'"positives": ["..."], "summary": "One paragraph overall assessment"}}'
        )

    @staticmethod
    def _parse_review_response(content: str, pr_number: int) -> ReviewResult:
        """Parse LLM JSON response. Falls back to empty findings on parse failure."""
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                return ReviewResult(
                    pr_number=pr_number,
                    critical=[Finding(**f) for f in data.get("critical", [])],
                    important=[Finding(**f) for f in data.get("important", [])],
                    suggestions=[Finding(**f) for f in data.get("suggestions", [])],
                    positives=data.get("positives", []),
                    summary=data.get("summary", ""),
                    github_comment_posted=False,
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Fallback: non-blocking, treat as advisory with raw content as summary
        return ReviewResult(
            pr_number=pr_number,
            critical=[],
            important=[],
            suggestions=[],
            positives=[],
            summary=content[:500],
            github_comment_posted=False,
        )

    @staticmethod
    def _format_github_comment(result: ReviewResult) -> str:
        """Format ReviewResult as a GitHub PR comment in markdown."""
        lines = [
            f"## NanoClaw AI Code Review — PR #{result.pr_number}",
            "",
            result.summary,
            "",
        ]
        if result.critical:
            lines.append("### 🔴 Critical (must fix before merge)")
            for f in result.critical:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Fix:** {f.fix}")
            lines.append("")
        if result.important:
            lines.append("### 🟡 Important (should fix)")
            for f in result.important:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Fix:** {f.fix}")
            lines.append("")
        if result.suggestions:
            lines.append("### 🔵 Suggestions (nice to have)")
            for f in result.suggestions:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Suggestion:** {f.fix}")
            lines.append("")
        if result.positives:
            lines.append("### ✅ Looks Good")
            for p in result.positives:
                lines.append(f"- {p}")
            lines.append("")
        lines.extend(["---", "*Generated by NanoClaw CodeReviewerAgent*"])
        return "\n".join(lines)

    @staticmethod
    def format_discord_summary(result: ReviewResult) -> str:
        """Short Discord-friendly summary — critical + important only."""
        lines = [
            f"**Code Review — PR #{result.pr_number}**",
            result.summary,
            "",
        ]
        if result.critical:
            lines.append("**🔴 Critical (must fix before merge):**")
            for f in result.critical:
                lines.append(f"- `{f.location}` — {f.issue}")
            lines.append("")
        if result.important:
            lines.append("**🟡 Important (should fix):**")
            for f in result.important:
                lines.append(f"- `{f.location}` — {f.issue}")
            lines.append("")
        if not result.critical and not result.important:
            lines.append("No critical or important issues found.")
        return "\n".join(lines)
```

- [ ] **Step 4: Run all new CodeReviewerAgent tests**

```bash
cd nanoclaw && python -m pytest tests/test_agents.py -k "code_reviewer or review_result" -v
```

Expected: `6 passed`

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/agents/code_reviewer.py nanoclaw/tests/test_agents.py
git commit -m "feat(code_reviewer): add CodeReviewerAgent with ReviewResult + Finding"
```

---

## Task 4: Create `code_reviewer_prompt.md`

The system prompt loaded by `CodeReviewerAgent._load_prompt()` at runtime.

**Files:**
- Create: `nanoclaw/config/prompts/code_reviewer_prompt.md`

- [ ] **Step 1: Create the prompt file**

Create `nanoclaw/config/prompts/code_reviewer_prompt.md`:

```markdown
# Code Reviewer Agent

You are an expert code reviewer embedded in an automated AI development pipeline. You review GitHub PR diffs for a software project and return structured findings.

## Your Role

You identify real problems that would cause bugs, security vulnerabilities, or maintenance pain. You are constructive and specific — you explain WHY something is a problem and HOW to fix it.

## Review Dimensions

For every change in the diff, evaluate:

**Correctness**
- Logic errors and edge cases (empty inputs, nil/None, zero values, boundary conditions)
- Error paths that are silently ignored or swallowed
- Concurrent access issues (data races, missing locks)
- Resource leaks (unclosed files, uncancelled contexts, missing defer/finally)

**Security**
- SQL injection (string interpolation in queries — always use parameterized queries)
- Command injection (user input passed to shell/exec)
- Authentication missing on protected endpoints
- Authorization checks missing (user can access another user's data)
- Sensitive data in logs, error messages, or API responses
- Missing input validation at system boundaries

**Performance**
- N+1 queries (a DB/API call inside a loop)
- Unbounded collections that grow without limit
- Unnecessary allocations or copies in hot paths
- Missing caching for expensive repeated operations

**Maintainability**
- Functions doing more than one thing
- Naming inconsistent with the rest of the codebase
- Logic duplicated elsewhere in the project
- Dead code or commented-out code left in

**Tests**
- New logic with no corresponding test
- Tests that only cover the happy path (missing error/edge case tests)
- Test names that describe implementation rather than behavior
- Mocks used where integration tests would catch more bugs

**Project Patterns**
- Error handling inconsistent with established patterns
- Logging inconsistent with the structured logging style
- Architectural layer boundaries crossed (e.g., HTTP handler calling DB directly)
- Import paths or module structure inconsistent with the codebase

## Output Format

Return ONLY valid JSON — no preamble, no explanation, no markdown fences. Any text outside the JSON will break the parser.

```json
{
  "critical": [
    {"location": "path/to/file.py:45", "issue": "One sentence describing the problem", "fix": "Specific actionable fix"}
  ],
  "important": [
    {"location": "path/to/file.py:78", "issue": "...", "fix": "..."}
  ],
  "suggestions": [
    {"location": "path/to/file.py:102", "issue": "...", "fix": "..."}
  ],
  "positives": [
    "Error handling matches the project's established pattern",
    "Test coverage includes the key edge cases"
  ],
  "summary": "One paragraph overall assessment of the change."
}
```

## Severity Guide

- **critical** — Security vulnerabilities, data loss risk, correctness bugs that will definitely cause failures. Must be fixed before this code can merge.
- **important** — Design issues, missing error handling, performance problems that will matter under load. Should be fixed.
- **suggestions** — Minor style improvements, refactoring opportunities, alternative approaches. Nice to have.
- **positives** — Things done well. Always include at least one if there is anything praiseworthy.

## Rules

- Reference every finding with `file.py:line_number` — never make vague claims
- If you are unsure whether something is a problem, err on the side of noting it as a suggestion
- If the diff is too small to assess meaningfully, say so in the summary and return empty arrays
- Return empty arrays for dimensions where you find no issues — never omit a key
```

- [ ] **Step 2: Verify the agent loads the prompt**

```bash
cd nanoclaw && python -c "
from agents.code_reviewer import CodeReviewerAgent
from unittest.mock import MagicMock, AsyncMock
agent = CodeReviewerAgent(MagicMock(), MagicMock(), MagicMock(), MagicMock())
prompt = agent._load_prompt()
print('Prompt loaded, length:', len(prompt))
assert 'Code Reviewer Agent' in prompt
print('OK')
"
```

Expected: `Prompt loaded, length: <N>` then `OK`

- [ ] **Step 3: Commit**

```bash
git add nanoclaw/config/prompts/code_reviewer_prompt.md
git commit -m "feat(prompts): add code_reviewer_prompt.md"
```

---

## Task 5: Update `ApprovalGate` — dual-signal + `resolve_by_pr`

The gate currently waits only for Discord reactions. We add:
1. Concurrent GitHub PR state polling (30s interval)
2. `resolve_by_pr(pr_number, approved)` for the `review override` command
3. `wait_for_github_merge(pr_number)` as a standalone awaitable

**Files:**
- Modify: `nanoclaw/workflow/approval_gate.py`
- Modify: `nanoclaw/tests/test_workflow_engine.py`

- [ ] **Step 1: Write the failing tests**

Add to `nanoclaw/tests/test_workflow_engine.py`:

```python
from agents.dev import PRInfo


# Helper — shared with new approval gate tests
def make_pr_info(number=42):
    return PRInfo(url=f"https://github.com/owner/repo/pull/{number}", number=number)


# --- ApprovalGate dual-signal tests ---

@pytest.mark.asyncio
async def test_approval_gate_github_merge_resolves_gate():
    """Gate resolves True when GitHub PR is merged before Discord reaction."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    # First call returns OPEN, second returns MERGED
    git.get_pr_state = AsyncMock(side_effect=["OPEN", "MERGED"])

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=0.05)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_github_close_resolves_false():
    """Gate resolves False when GitHub PR is closed."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="CLOSED")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=0.05)
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_discord_wins_over_github():
    """Discord reaction resolves gate before GitHub polling does."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    # GitHub never merges within test
    async def slow_poll(*args, **kwargs):
        await asyncio.sleep(10)
        return False
    git.get_pr_state = AsyncMock(return_value="OPEN")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    async def approve_via_discord():
        await asyncio.sleep(0.05)
        gate.resolve("TASK-001", True)

    asyncio.create_task(approve_via_discord())
    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=10)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_resolve_by_pr():
    """resolve_by_pr finds and resolves the gate for a given PR number."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="OPEN")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    async def override_after_delay():
        await asyncio.sleep(0.05)
        resolved = gate.resolve_by_pr(42, True)
        assert resolved is True

    asyncio.create_task(override_after_delay())
    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(42),
                                poll_interval_seconds=10)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_resolve_by_pr_not_found():
    """resolve_by_pr returns False when no gate exists for the PR number."""
    bot = MagicMock()
    gate = ApprovalGate(bot, timeout_minutes=1)
    result = gate.resolve_by_pr(999, True)
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_wait_for_github_merge_merged():
    """wait_for_github_merge returns True when state becomes MERGED."""
    bot = MagicMock()
    git = MagicMock()
    git.get_pr_state = AsyncMock(side_effect=["OPEN", "OPEN", "MERGED"])

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    result = await gate.wait_for_github_merge(42, poll_interval_seconds=0.01)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_wait_for_github_merge_closed():
    """wait_for_github_merge returns False when state becomes CLOSED."""
    bot = MagicMock()
    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="CLOSED")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    result = await gate.wait_for_github_merge(42, poll_interval_seconds=0.01)
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py::test_approval_gate_github_merge_resolves_gate -v
```

Expected: `FAILED` — `TypeError: ApprovalGate.__init__() got an unexpected keyword argument 'git'`

- [ ] **Step 3: Rewrite `nanoclaw/workflow/approval_gate.py`**

```python
"""ApprovalGate — Discord + GitHub dual-signal approval for task PRs."""
import asyncio
import logging
from typing import Optional

import discord

from agents.dev import DevResult, PRInfo

logger = logging.getLogger("nanoclaw.approval_gate")

APPROVE_EMOJI = "\u2705"  # ✅
REJECT_EMOJI = "\u274c"   # ❌


class ApprovalGate:
    def __init__(self, bot: discord.Client,
                 git=None,
                 timeout_minutes: int = 60):
        self.bot = bot
        self.git = git
        self.timeout = timeout_minutes * 60
        # task_id -> asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # pr_number -> task_id (for resolve_by_pr)
        self._pr_to_task: dict[int, str] = {}

    async def request(self, task: dict, dev_result: DevResult,
                      pr_info: Optional[PRInfo] = None,
                      poll_interval_seconds: int = 30) -> bool:
        """
        Post approval message to Discord thread.
        If pr_info provided, also polls GitHub state concurrently.
        Whichever signal arrives first (Discord reaction or GitHub state
        change) resolves the gate.
        Returns True if approved/merged, False if rejected/closed/timed out.
        """
        thread_id = task.get("discord_thread_id")
        if not thread_id:
            logger.warning("No discord_thread_id for task %s, auto-rejecting",
                           task["id"])
            return False

        channel = self.bot.get_channel(int(thread_id))
        if not channel:
            logger.warning("Thread %s not found, auto-rejecting", thread_id)
            return False

        # Build approval message
        files_list = "\n".join(
            f"  - `{f}`" for f in dev_result.files_changed[:20]
        )
        pr_line = f"**PR:** {pr_info.url}\n" if pr_info else ""
        msg_text = (
            f"**Task {task['id']}** ready for review\n\n"
            f"{pr_line}"
            f"**Branch:** `{dev_result.branch}`\n"
            f"**Files changed ({len(dev_result.files_changed)}):**\n{files_list}\n\n"
            f"React {APPROVE_EMOJI} to approve or {REJECT_EMOJI} to reject.\n"
            f"_(You may also merge or close the PR directly on GitHub.)_"
        )
        msg = await channel.send(msg_text)
        await msg.add_reaction(APPROVE_EMOJI)
        await msg.add_reaction(REJECT_EMOJI)

        # Create Discord future
        loop = asyncio.get_running_loop()
        discord_future = loop.create_future()
        self._pending[task["id"]] = discord_future
        if pr_info:
            self._pr_to_task[pr_info.number] = task["id"]

        github_task = None
        try:
            if pr_info and self.git:
                github_task = asyncio.ensure_future(
                    self.wait_for_github_merge(
                        pr_info.number,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                )
                done, _ = await asyncio.wait(
                    {discord_future, github_task},
                    timeout=self.timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    logger.info("Approval timed out for task %s", task["id"])
                    await channel.send(
                        f"Approval for **{task['id']}** timed out after "
                        f"{self.timeout // 60} minutes. Task cancelled."
                    )
                    return False
                return next(iter(done)).result()
            else:
                approved = await asyncio.wait_for(
                    discord_future, timeout=self.timeout
                )
                return approved
        except asyncio.TimeoutError:
            logger.info("Approval timed out for task %s", task["id"])
            await channel.send(
                f"Approval for **{task['id']}** timed out after "
                f"{self.timeout // 60} minutes. Task cancelled."
            )
            return False
        finally:
            self._pending.pop(task["id"], None)
            if pr_info:
                self._pr_to_task.pop(pr_info.number, None)
            if github_task and not github_task.done():
                github_task.cancel()

    async def wait_for_github_merge(self, pr_number: int,
                                    poll_interval_seconds: int = 30) -> bool:
        """Poll GitHub PR state. Returns True on MERGED, False on CLOSED."""
        while True:
            state = await self.git.get_pr_state(pr_number)
            if state == "MERGED":
                logger.info("PR #%d merged on GitHub", pr_number)
                return True
            if state == "CLOSED":
                logger.info("PR #%d closed on GitHub", pr_number)
                return False
            await asyncio.sleep(poll_interval_seconds)

    def resolve(self, task_id: str, approved: bool) -> None:
        """Called by bot's on_reaction_add — resolves the pending Discord future."""
        future = self._pending.get(task_id)
        if future and not future.done():
            future.set_result(approved)
            logger.info("Task %s %s via Discord reaction", task_id,
                        "approved" if approved else "rejected")

    def resolve_by_pr(self, pr_number: int, approved: bool) -> bool:
        """Called by 'review override' command — resolves gate by PR number.
        Returns True if a pending gate was found and resolved, False otherwise."""
        task_id = self._pr_to_task.get(pr_number)
        if not task_id:
            logger.warning("No pending gate found for PR #%d", pr_number)
            return False
        self.resolve(task_id, approved)
        return True

    def get_pending_task_ids(self) -> list[str]:
        """Return list of task IDs currently awaiting approval."""
        return list(self._pending.keys())
```

- [ ] **Step 4: Run all new ApprovalGate tests**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py -k "approval_gate" -v
```

Expected: all approval gate tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/workflow/approval_gate.py nanoclaw/tests/test_workflow_engine.py
git commit -m "feat(approval_gate): dual-signal gate — Discord reaction + GitHub merge polling"
```

---

## Task 6: Restructure `WorkflowEngine._run_task`

Add `code_reviewer` to the engine; restructure the task pipeline to: QA → commit_and_push (PRInfo) → code review → conditional gate; update existing tests.

**Files:**
- Modify: `nanoclaw/workflow/engine.py`
- Modify: `nanoclaw/tests/test_workflow_engine.py`

- [ ] **Step 1: Update the `mock_dev` fixture and write new engine tests**

In `nanoclaw/tests/test_workflow_engine.py`, find the `mock_dev` fixture and update:

```python
@pytest.fixture
def mock_dev():
    dev = MagicMock()
    dev.implement = AsyncMock(return_value=make_dev_result())
    # Now returns PRInfo instead of str
    dev.commit_and_push = AsyncMock(
        return_value=PRInfo(
            url="https://github.com/owner/repo/pull/1", number=1
        )
    )
    return dev
```

Add a `mock_code_reviewer` fixture:

```python
from agents.code_reviewer import CodeReviewerAgent, ReviewResult, Finding

def make_review_result(has_critical=False, pr_number=1):
    critical = [
        Finding(location="a.py:1", issue="SQL injection", fix="Use params")
    ] if has_critical else []
    return ReviewResult(
        pr_number=pr_number,
        critical=critical,
        important=[],
        suggestions=[],
        positives=["Clean code"],
        summary="Review complete.",
        github_comment_posted=True,
    )

@pytest.fixture
def mock_code_reviewer():
    reviewer = MagicMock()
    reviewer.review = AsyncMock(return_value=make_review_result())
    reviewer.format_discord_summary = CodeReviewerAgent.format_discord_summary
    return reviewer
```

Update the `engine` fixture to include `mock_code_reviewer`:

```python
@pytest.fixture
def engine(mock_pm, mock_dev, mock_qa, mock_code_reviewer,
           mock_task_store, mock_gate):
    return WorkflowEngine(
        pm=mock_pm, dev=mock_dev, qa=mock_qa,
        code_reviewer=mock_code_reviewer,
        task_store=mock_task_store,
        approval_gate=mock_gate,
    )
```

Add new engine tests:

```python
@pytest.mark.asyncio
async def test_run_feature_code_review_called_after_qa(
    engine, mock_dev, mock_qa, mock_code_reviewer, mock_gate
):
    """Code review runs after QA passes, before approval gate."""
    result = await engine.run_feature("Add health endpoint")
    assert result["tasks"][0]["success"] is True
    # commit_and_push called before code review
    mock_dev.commit_and_push.assert_called_once()
    mock_code_reviewer.review.assert_called_once()
    # approval gate called after review
    mock_gate.request.assert_called_once()


@pytest.mark.asyncio
async def test_run_feature_critical_findings_skip_discord_gate(
    mock_pm, mock_dev, mock_qa, mock_task_store
):
    """Critical findings bypass Discord gate — waits for GitHub merge only."""
    gate = MagicMock()
    gate.request = AsyncMock(return_value=True)
    gate.wait_for_github_merge = AsyncMock(return_value=True)

    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=make_review_result(has_critical=True)
    )
    reviewer.format_discord_summary = CodeReviewerAgent.format_discord_summary

    engine = WorkflowEngine(
        pm=mock_pm, dev=mock_dev, qa=mock_qa,
        code_reviewer=reviewer,
        task_store=mock_task_store,
        approval_gate=gate,
    )
    result = await engine.run_feature("Add feature")

    # Discord gate NOT called for critical findings
    gate.request.assert_not_called()
    # GitHub merge waited on instead
    gate.wait_for_github_merge.assert_called_once()
    assert result["tasks"][0]["success"] is True


@pytest.mark.asyncio
async def test_run_feature_pr_url_from_prinfo(engine):
    """pr_url in result comes from PRInfo.url."""
    result = await engine.run_feature("Add feature")
    assert result["tasks"][0]["pr_url"] == "https://github.com/owner/repo/pull/1"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py::test_run_feature_code_review_called_after_qa -v
```

Expected: `FAILED` — `TypeError: WorkflowEngine.__init__() got an unexpected keyword argument 'code_reviewer'`

- [ ] **Step 3: Update `nanoclaw/workflow/engine.py`**

Update the import at the top:

```python
from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent
from agents.code_reviewer import CodeReviewerAgent
from memory.task_store import TaskStore
from workflow.approval_gate import ApprovalGate
```

Update `__init__`:

```python
def __init__(self, pm: PMAgent, dev: DevAgent, qa: QAAgent,
             code_reviewer: CodeReviewerAgent,
             task_store: TaskStore, approval_gate: ApprovalGate,
             max_retries: int = DEFAULT_MAX_RETRIES,
             progress_callback=None):
    self.pm = pm
    self.dev = dev
    self.qa = qa
    self.code_reviewer = code_reviewer
    self.task_store = task_store
    self.gate = approval_gate
    self._max_retries = max_retries
    self._progress = progress_callback or self._noop_progress
```

Replace `_run_task` entirely:

```python
async def _run_task(self, task: dict, session_id: str) -> dict:
    """Dev → QA → commit/push → CodeReview → gate loop for one task."""
    max_retries = task.get("max_retries", self._max_retries)
    for attempt in range(max_retries + 1):
        await self._progress(
            f"Dev working on {task['id']} "
            f"(attempt {attempt + 1}/{max_retries + 1})..."
        )
        dev_result = await self.dev.implement(task, session_id)

        if not dev_result.verification_passed:
            if attempt >= max_retries:
                await self._progress(
                    f"{task['id']} verification failed after "
                    f"{max_retries} retries. Manual intervention needed."
                )
                return {"task_id": task["id"], "success": False,
                        "reason": "verification failed, max retries exceeded",
                        "details": dev_result.error}
            await self.task_store.increment_retry(task["id"])
            continue

        await self._progress(f"QA validating {task['id']}...")
        qa_result = await self.qa.handle(
            task=task, dev_result=dev_result, session_id=session_id
        )

        if not qa_result["passed"]:
            if attempt >= max_retries:
                await self._progress(
                    f"{task['id']} failed after {max_retries} retries. "
                    f"Manual intervention needed."
                )
                await self.task_store.update(task["id"], status="failed")
                return {"task_id": task["id"], "success": False,
                        "reason": "max retries exceeded",
                        "qa_result": qa_result}
            await self.task_store.increment_retry(task["id"])
            continue

        # QA passed — create PR
        await self._progress(f"{task['id']} QA passed — creating PR...")
        pr_info = await self.dev.commit_and_push(task, dev_result)

        # Run code review
        await self._progress(
            f"PR created: {pr_info.url} — running code review..."
        )
        review = await self.code_reviewer.review(
            pr_number=pr_info.number,
            task_id=task["id"],
            session_id=session_id,
        )

        review_summary = CodeReviewerAgent.format_discord_summary(review)

        if review.has_critical:
            await self._progress(
                f"🔴 Critical issues found on PR #{pr_info.number}. "
                f"Fix them and merge on GitHub, or use "
                f"`review override {pr_info.number}` to force-approve.\n\n"
                + review_summary
            )
            merged = await self.gate.wait_for_github_merge(pr_info.number)
            return {"task_id": task["id"], "success": merged,
                    "pr_url": pr_info.url}

        await self._progress(
            f"✅ Code review complete. Awaiting your approval.\n\n"
            + review_summary
        )
        approved = await self.gate.request(
            task, dev_result, pr_info=pr_info
        )
        if approved:
            return {"task_id": task["id"], "success": True,
                    "pr_url": pr_info.url}
        else:
            await self.task_store.update(task["id"], status="failed")
            return {"task_id": task["id"], "success": False,
                    "reason": "rejected by user"}

    return {"task_id": task["id"], "success": False, "reason": "unknown"}
```

- [ ] **Step 4: Run all engine tests**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py -k "engine" -v
```

Expected: all engine tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/workflow/engine.py nanoclaw/tests/test_workflow_engine.py
git commit -m "feat(engine): restructure _run_task — QA → PR → code review → gate"
```

---

## Task 7: Update `Orchestrator` with `review` commands

Add two new commands: `review <pr_number>` (on-demand review of any PR) and `review override <pr_number>` (force-approve a PR blocked by critical findings).

**Files:**
- Modify: `nanoclaw/orchestrator.py`
- Modify: `nanoclaw/tests/test_workflow_engine.py`

- [ ] **Step 1: Write the failing tests**

Add to `nanoclaw/tests/test_workflow_engine.py`:

```python
from agents.code_reviewer import ReviewResult, Finding


def make_clean_review(pr_number=42):
    return ReviewResult(
        pr_number=pr_number, critical=[], important=[],
        suggestions=[], positives=["Clean"], summary="All good.",
        github_comment_posted=True,
    )


@pytest.fixture
def orchestrator_with_reviewer():
    engine = MagicMock()
    engine.run_feature = AsyncMock(return_value={"session_id": "abc", "tasks": []})
    engine.run_single_task = AsyncMock(return_value={
        "task_id": "TASK-001", "success": True,
        "pr_url": "https://github.com/owner/repo/pull/1",
    })
    engine._noop_progress = AsyncMock()

    task_store = MagicMock()
    task_store.get = AsyncMock(return_value=make_task())
    task_store.update = AsyncMock()
    task_store.list_tasks = AsyncMock(return_value=[make_task(status="open")])

    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock()
    job_queue.stop = AsyncMock()
    job_queue.resume = AsyncMock()
    job_queue.active_count = 0
    job_queue.queued_count = 0
    job_queue.is_stopped = False

    cost_tracker = MagicMock()
    cost_tracker.daily_total = AsyncMock(return_value=0.0)

    code_reviewer = MagicMock()
    code_reviewer.review = AsyncMock(return_value=make_clean_review())

    gate = MagicMock()
    gate.resolve_by_pr = MagicMock(return_value=True)

    return Orchestrator(
        engine=engine,
        task_store=task_store,
        job_queue=job_queue,
        cost_tracker=cost_tracker,
        code_reviewer=code_reviewer,
        approval_gate=gate,
    )


@pytest.mark.asyncio
async def test_orchestrator_review_enqueues_job(orchestrator_with_reviewer):
    result = await orchestrator_with_reviewer.handle("review 42", "user1")
    assert "Queued" in result
    assert "42" in result
    orchestrator_with_reviewer.job_queue.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_review_missing_number(orchestrator_with_reviewer):
    result = await orchestrator_with_reviewer.handle("review", "user1")
    assert "Usage" in result


@pytest.mark.asyncio
async def test_orchestrator_review_invalid_number(orchestrator_with_reviewer):
    result = await orchestrator_with_reviewer.handle("review abc", "user1")
    assert "valid integer" in result.lower() or "Usage" in result


@pytest.mark.asyncio
async def test_orchestrator_review_override_resolves_gate(orchestrator_with_reviewer):
    result = await orchestrator_with_reviewer.handle("review override 42", "user1")
    assert "override" in result.lower() or "approved" in result.lower()
    orchestrator_with_reviewer.approval_gate.resolve_by_pr.assert_called_once_with(42, True)


@pytest.mark.asyncio
async def test_orchestrator_review_override_not_found(orchestrator_with_reviewer):
    orchestrator_with_reviewer.approval_gate.resolve_by_pr = MagicMock(return_value=False)
    result = await orchestrator_with_reviewer.handle("review override 999", "user1")
    assert "no pending" in result.lower() or "not found" in result.lower()


@pytest.mark.asyncio
async def test_orchestrator_usage_includes_review():
    """usage string mentions the review command."""
    result = Orchestrator._usage()
    assert "review" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py::test_orchestrator_review_enqueues_job -v
```

Expected: `FAILED` — `TypeError: Orchestrator.__init__() got an unexpected keyword argument 'code_reviewer'`

- [ ] **Step 3: Update `nanoclaw/orchestrator.py`**

Update `__init__`:

```python
def __init__(self, engine: WorkflowEngine,
             task_store: TaskStore,
             job_queue: JobQueue,
             cost_tracker: CostTracker,
             code_reviewer=None,
             approval_gate=None,
             rate_limiter: RateLimiter | None = None,
             budget_guard: BudgetGuard | None = None):
    self.engine = engine
    self.task_store = task_store
    self.job_queue = job_queue
    self.cost_tracker = cost_tracker
    self.code_reviewer = code_reviewer
    self.approval_gate = approval_gate
    self.rate_limiter = rate_limiter
    self.budget_guard = budget_guard
```

In `handle()`, add routing for `review` before the return `self._usage()`:

```python
# Review commands
if keyword == "review":
    if len(parts) >= 2 and parts[1].lower() == "override":
        raw = parts[2] if len(parts) >= 3 else None
        try:
            pr_number = int(raw) if raw else None
        except ValueError:
            pr_number = None
        return await self._handle_review_override(pr_number)

    raw = parts[1] if len(parts) >= 2 else None
    try:
        pr_number = int(raw) if raw else None
    except ValueError:
        return "Usage: `review <pr_number>` — pr_number must be a valid integer"
    return await self._handle_review(pr_number, thread_id, progress_callback)
```

Also add `"review"` to the safety-gated keyword set in `handle()`:

```python
if keyword in ("pm", "dev", "feature", "build", "implement", "review"):
    blocked = await self._check_safety_gates()
    if blocked:
        return blocked
```

Add the two new handler methods:

```python
async def _handle_review(self, pr_number: int | None,
                         thread_id, progress_callback) -> str:
    if pr_number is None:
        return "Usage: `review <pr_number>`"
    if not self.code_reviewer:
        return "Code reviewer not configured."

    session_id = str(uuid.uuid4())

    async def job_fn():
        review = await self.code_reviewer.review(
            pr_number=pr_number, session_id=session_id,
        )
        if progress_callback:
            from agents.code_reviewer import CodeReviewerAgent
            summary = CodeReviewerAgent.format_discord_summary(review)
            await progress_callback(summary)

    job = Job(
        id=f"review-{pr_number}-{session_id[:8]}",
        fn=job_fn,
        discord_thread_id=thread_id,
    )
    await self.job_queue.enqueue(job)
    return f"Queued code review for PR #{pr_number}."

async def _handle_review_override(self, pr_number: int | None) -> str:
    if pr_number is None:
        return "Usage: `review override <pr_number>`"
    if not self.approval_gate:
        return "Approval gate not configured."

    resolved = self.approval_gate.resolve_by_pr(pr_number, True)
    if resolved:
        return (
            f"Override applied: PR #{pr_number} force-approved. "
            f"Pipeline will proceed."
        )
    return (
        f"No pending approval gate found for PR #{pr_number}. "
        f"Nothing to override."
    )
```

Update `_usage()`:

```python
@staticmethod
def _usage() -> str:
    return (
        "**Commands:**\n"
        "  `PM define <instruction>` — Create spec + tasks\n"
        "  `Dev implement <task_id>` — Implement a specific task\n"
        "  `feature <instruction>` — Shorthand for PM define\n"
        "  `review <pr_number>` — AI code review on any PR\n"
        "  `review override <pr_number>` — Force-approve a PR blocked by critical findings\n"
        "  `status` — Show current status\n"
        "  `cost` — Show today's LLM costs\n"
        "  `STOP` — Halt job queue\n"
        "  `RESUME` — Resume job queue"
    )
```

- [ ] **Step 4: Run all new orchestrator tests**

```bash
cd nanoclaw && python -m pytest tests/test_workflow_engine.py -k "review" -v
```

Expected: all review command tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nanoclaw/orchestrator.py nanoclaw/tests/test_workflow_engine.py
git commit -m "feat(orchestrator): add 'review' and 'review override' Discord commands"
```

---

## Task 8: Update `bot.py` wiring

Wire `CodeReviewerAgent` into the bot and pass it through to `WorkflowEngine`, `ApprovalGate`, and `Orchestrator`.

**Files:**
- Modify: `nanoclaw/bot.py`

- [ ] **Step 1: Update `bot.py`**

Add import after the existing agent imports:

```python
from agents.code_reviewer import CodeReviewerAgent
```

In `NanoClawBot.__init__`, add after `self.qa = ...`:

```python
self.code_reviewer = CodeReviewerAgent(
    self.router, self.memory, self.context_loader, self.git,
)
```

Update `ApprovalGate` instantiation (add `git=`):

```python
self.approval_gate = ApprovalGate(
    self.client,
    git=self.git,
    timeout_minutes=settings.workflow.approval_timeout_minutes,
)
```

Update `WorkflowEngine` instantiation (add `code_reviewer=`):

```python
self.engine = WorkflowEngine(
    pm=self.pm, dev=self.dev, qa=self.qa,
    code_reviewer=self.code_reviewer,
    task_store=self.task_store,
    approval_gate=self.approval_gate,
    max_retries=settings.workflow.max_retries,
)
```

Update `Orchestrator` instantiation (add `code_reviewer=` and `approval_gate=`):

```python
self.orchestrator = Orchestrator(
    engine=self.engine,
    task_store=self.task_store,
    job_queue=self.job_queue,
    cost_tracker=self.cost_tracker,
    code_reviewer=self.code_reviewer,
    approval_gate=self.approval_gate,
    rate_limiter=self.rate_limiter,
    budget_guard=self.budget_guard,
)
```

Update `_is_task_command` to include `review`:

```python
@staticmethod
def _is_task_command(command: str) -> bool:
    cmd_lower = command.lower()
    return any(cmd_lower.startswith(prefix) for prefix in (
        "pm ", "dev ", "implement ", "build ", "feature ", "review ",
    ))
```

- [ ] **Step 2: Verify bot imports cleanly**

```bash
cd nanoclaw && python -c "
import os, sys
os.environ['DISCORD_BOT_TOKEN'] = 'fake'
os.environ['ANTHROPIC_API_KEY'] = 'fake'
# Patch discord to avoid needing a real connection
from unittest.mock import MagicMock, patch
with patch('discord.Client'):
    from bot import NanoClawBot
print('bot.py imports OK')
"
```

Expected: `bot.py imports OK`

- [ ] **Step 3: Run full test suite**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add nanoclaw/bot.py
git commit -m "feat(bot): wire CodeReviewerAgent into engine, gate, and orchestrator"
```

---

## Task 9: Create `.claude/agents/code-reviewer.md`

Agent spec for Claude Code workflows — fills the gap where `/review-code` had no agent identity.

**Files:**
- Create: `.claude/agents/code-reviewer.md`

- [ ] **Step 1: Create the agent spec file**

Create `.claude/agents/code-reviewer.md`:

```markdown
---
name: code-reviewer
description: AI code reviewer for GitHub PRs and local diffs. Reviews for correctness, security, performance, maintainability, test coverage, and project pattern adherence. Called automatically by NanoClaw pipeline after PR creation, or manually via `@NanoClaw review <pr_number>`.
---

# Code Reviewer Agent

## Purpose

Perform thorough, structured code review on GitHub PR diffs or local git diffs. Produce severity-bucketed findings with exact file:line references and specific fix suggestions.

## When This Agent Is Used

**Automated (NanoClaw pipeline):**
After QA passes and a PR is created, `WorkflowEngine` calls `CodeReviewerAgent.review(pr_number)`. The agent fetches the diff via `gh pr diff`, runs the LLM review, posts findings to GitHub as a PR comment, and returns a `ReviewResult` to the engine.

**Manual (Discord command):**
`@NanoClaw review <pr_number>` — reviews any PR in the configured repo, not just NanoClaw PRs.

**Manual (Claude Code CLI):**
Invoke `/review-code` in the terminal to review the current git diff, a specific file, or a branch.

## Output Format

```markdown
## Code Review: [Target]
Date: YYYY-MM-DD

### Summary
[1-2 sentence overall assessment]

### 🔴 Critical (must fix before merge)
- `path/to/file.py:45` — SQL query uses string interpolation → SQL injection risk
  **Fix:** Use parameterized query: `db.query("... WHERE id = $1", id)`

### 🟡 Important (should fix)
- `path/to/file.py:78` — Error from `cache.set()` is silently ignored
  **Fix:** Log the error: `if err != nil { logger.warn("cache set failed", err) }`

### 🔵 Suggestions (nice to have)
- `path/to/file.py:102` — Logic duplicates `pkg/utils/validate.py:34`
  **Suggestion:** Extract to shared function or reuse existing

### ✅ Looks Good
- Error handling pattern matches project conventions
- Test coverage includes edge cases
```

## Review Dimensions

| Dimension | What to check |
|---|---|
| **Correctness** | Logic errors, unhandled edge cases (nil/None/empty/zero), swallowed errors, data races, resource leaks |
| **Security** | SQL/command injection, missing auth/authz, sensitive data in logs, missing input validation |
| **Performance** | N+1 queries, unbounded collections, unnecessary allocations in hot paths |
| **Maintainability** | Single responsibility, consistent naming, no duplication, no dead code |
| **Tests** | New logic has tests, error/edge cases covered, test names describe behavior |
| **Patterns** | Error handling, logging, architectural layer boundaries, import conventions |

## Rules

- Reference every finding with exact `file:line` — never make vague claims
- Explain WHY each issue is a problem, not just that it is
- Provide a specific fix, not just "fix this"
- Acknowledge what is done well — reviews are constructive, not just critical
- Severity guide:
  - **Critical:** Will cause bugs, security holes, or data loss — must fix before merge
  - **Important:** Should fix — design issues, perf under load, missing error handling
  - **Suggestions:** Nice to have — style, minor refactors, alternatives

## Blocking Behaviour (Pipeline)

If the review returns any **Critical** findings:
- Discord approval message is withheld
- Bot posts a warning in the Discord thread
- Human must either merge/close on GitHub, or issue `@NanoClaw review override <pr_number>`

If no Critical findings:
- Approval gate opens (Discord ✅/❌ reaction OR GitHub merge — whichever first)
```

- [ ] **Step 2: Run full test suite one final time**

```bash
cd nanoclaw && python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/code-reviewer.md
git commit -m "docs(agents): add code-reviewer agent spec"
```

---

## Done

All tasks complete. The full pipeline is now:

```
@NanoClaw PM define <instruction>
  → PMAgent creates tasks
  → DevAgent implements in worktree
  → QAAgent validates acceptance criteria
  → DevAgent commits + pushes + opens PR  ← PR created here
  → CodeReviewerAgent fetches diff, reviews, posts GitHub comment
  → if 🔴 Critical: warn in Discord, wait for GitHub merge or 'review override'
  → if clean: ApprovalGate (Discord ✅/❌ OR GitHub merge, first wins)
```

Manual commands added:
- `@NanoClaw review <pr_number>` — on-demand review of any PR
- `@NanoClaw review override <pr_number>` — force-approve a blocked PR
```
