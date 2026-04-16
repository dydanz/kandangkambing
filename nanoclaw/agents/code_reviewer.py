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
    critical: list[Finding]       # must fix before merge
    important: list[Finding]      # should fix
    suggestions: list[Finding]    # nice to have
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
            lines.append("### Critical (must fix before merge)")
            for f in result.critical:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Fix:** {f.fix}")
            lines.append("")
        if result.important:
            lines.append("### Important (should fix)")
            for f in result.important:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Fix:** {f.fix}")
            lines.append("")
        if result.suggestions:
            lines.append("### Suggestions (nice to have)")
            for f in result.suggestions:
                lines.append(f"- **`{f.location}`** — {f.issue}")
                lines.append(f"  - **Suggestion:** {f.fix}")
            lines.append("")
        if result.positives:
            lines.append("### Looks Good")
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
            lines.append("**Critical (must fix before merge):**")
            for f in result.critical:
                lines.append(f"- `{f.location}` — {f.issue}")
            lines.append("")
        if result.important:
            lines.append("**Important (should fix):**")
            for f in result.important:
                lines.append(f"- `{f.location}` — {f.issue}")
            lines.append("")
        if not result.critical and not result.important:
            lines.append("No critical or important issues found.")
        return "\n".join(lines)
