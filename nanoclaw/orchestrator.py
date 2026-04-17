"""NanoClaw Orchestrator — command parsing and routing."""
import logging
import uuid
from typing import Callable, Awaitable, Optional

from memory.task_store import TaskStore
from memory.cost_tracker import CostTracker
from workflow.engine import WorkflowEngine
from workflow.job_queue import JobQueue, Job
from safety.rate_limiter import RateLimiter
from safety.budget_guard import BudgetGuard

logger = logging.getLogger("nanoclaw.orchestrator")


class Orchestrator:
    """Parses Discord commands and routes to the appropriate handler.

    Commands:
        PM define <instruction>   — Create spec + tasks via PM agent
        Dev implement <task_id>   — Run Dev→QA loop for a specific task
        status                    — Show active jobs, queue depth, spend
        STOP                      — Halt job queue
        RESUME                    — Resume job queue
        cost                      — Show today's cost breakdown
    """

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

    async def handle(self, command: str, user_id: str,
                     thread_id: Optional[str] = None,
                     progress_callback: Optional[Callable] = None) -> str:
        """Parse and route a command. Returns response text."""
        logger.info("Received command from %s: %s", user_id, command)

        parts = command.strip().split(maxsplit=2)
        if not parts:
            return self._usage()

        keyword = parts[0].lower()

        # System commands
        if keyword == "stop":
            return await self._handle_stop()
        if keyword == "resume":
            return await self._handle_resume()
        if keyword == "status":
            return await self._handle_status()
        if keyword == "cost":
            return await self._handle_cost()

        # review override makes no LLM calls — exempt from safety gates
        if keyword == "review" and len(parts) >= 2 and parts[1].lower() == "override":
            raw = parts[2] if len(parts) >= 3 else None
            try:
                pr_number = int(raw) if raw else None
            except ValueError:
                pr_number = None
            return await self._handle_review_override(pr_number)

        # Safety checks for work commands (review override already handled above)
        if keyword in ("pm", "dev", "feature", "build", "implement", "review"):
            blocked = await self._check_safety_gates()
            if blocked:
                return blocked

        # PM commands
        if keyword == "pm" and len(parts) >= 2:
            sub = parts[1].lower()
            if sub == "define" and len(parts) >= 3:
                instruction = parts[2]
                return await self._handle_pm_define(
                    instruction, thread_id, progress_callback,
                )
            return "Usage: `PM define <instruction>`"

        # Dev commands
        if keyword == "dev" and len(parts) >= 2:
            sub = parts[1].lower()
            if sub == "implement" and len(parts) >= 3:
                task_id = parts[2].strip()
                return await self._handle_dev_implement(
                    task_id, thread_id, progress_callback,
                )
            return "Usage: `Dev implement <task_id>`"

        # Feature shorthand — treat as PM define
        if keyword in ("feature", "build", "implement"):
            instruction = command[len(keyword):].strip()
            if instruction:
                return await self._handle_pm_define(
                    instruction, thread_id, progress_callback,
                )

        # Review command (override already handled before safety gate above)
        if keyword == "review":
            raw = parts[1] if len(parts) >= 2 else None
            try:
                pr_number = int(raw) if raw else None
            except ValueError:
                return "Usage: `review <pr_number>` — pr_number must be a valid integer"
            return await self._handle_review(pr_number, thread_id, progress_callback)

        return self._usage()

    async def _check_safety_gates(self) -> str | None:
        """Run budget and rate limit checks. Returns error message or None."""
        if self.budget_guard:
            allowed, msg = await self.budget_guard.check()
            if not allowed:
                return msg

        if self.rate_limiter:
            allowed, msg = self.rate_limiter.check("llm_calls")
            if not allowed:
                return msg

        return None

    async def _handle_pm_define(self, instruction: str,
                                thread_id: Optional[str],
                                progress_callback: Optional[Callable]) -> str:
        """Enqueue a full PM→Dev→QA workflow."""
        session_id = str(uuid.uuid4())

        async def job_fn():
            self.engine._progress = progress_callback or self.engine._noop_progress
            result = await self.engine.run_feature(
                instruction, session_id=session_id,
            )
            # Post summary
            if progress_callback:
                summary = self._format_feature_result(result)
                await progress_callback(summary)

        job = Job(
            id=f"feature-{session_id[:8]}",
            fn=job_fn,
            discord_thread_id=thread_id,
        )
        await self.job_queue.enqueue(job)
        return f"Queued feature request. Session: `{session_id[:8]}`"

    async def _handle_dev_implement(self, task_id: str,
                                    thread_id: Optional[str],
                                    progress_callback: Optional[Callable]) -> str:
        """Enqueue a single-task Dev→QA loop."""
        session_id = str(uuid.uuid4())

        # Inject thread_id into task for approval gate
        task = await self.task_store.get(task_id)
        if not task:
            return f"Task `{task_id}` not found."

        if thread_id:
            await self.task_store.update(task_id, discord_thread_id=thread_id)

        async def job_fn():
            self.engine._progress = progress_callback or self.engine._noop_progress
            result = await self.engine.run_single_task(
                task_id, session_id=session_id,
            )
            if progress_callback:
                status = "succeeded" if result.get("success") else "failed"
                reason = result.get("reason", "")
                pr_url = result.get("pr_url", "")
                msg = f"Task `{task_id}` {status}."
                if pr_url:
                    msg += f" PR: {pr_url}"
                if reason:
                    msg += f" Reason: {reason}"
                await progress_callback(msg)

        job = Job(
            id=f"task-{task_id}",
            fn=job_fn,
            discord_thread_id=thread_id,
        )
        await self.job_queue.enqueue(job)
        return f"Queued task `{task_id}` for implementation."

    async def _handle_stop(self) -> str:
        await self.job_queue.stop()
        return "Job queue **stopped**. No new jobs will be processed. Use `RESUME` to restart."

    async def _handle_resume(self) -> str:
        await self.job_queue.resume()
        return "Job queue **resumed**."

    async def _handle_status(self) -> str:
        active = self.job_queue.active_count
        queued = self.job_queue.queued_count
        stopped = self.job_queue.is_stopped
        daily_cost = await self.cost_tracker.daily_total()

        tasks = await self.task_store.list_tasks()
        open_count = sum(1 for t in tasks if t.get("status") == "open")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        done_count = sum(1 for t in tasks if t.get("status") == "done")

        status_text = (
            f"**NanoClaw Status**\n"
            f"Queue: {'STOPPED' if stopped else 'running'} | "
            f"Active jobs: {active} | Queued: {queued}\n"
            f"Tasks: {open_count} open, {in_progress} in-progress, "
            f"{done_count} done\n"
            f"Today's spend: ${daily_cost:.2f}"
        )
        return status_text

    async def _handle_cost(self) -> str:
        daily = await self.cost_tracker.daily_total()
        if daily == 0.0:
            return "No LLM costs recorded today."
        return f"**Today's LLM spend:** ${daily:.4f}"

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

        async def on_error_fn(exc: Exception) -> None:
            if progress_callback:
                await progress_callback(
                    f"Code review for PR #{pr_number} failed: {exc}"
                )

        job = Job(
            id=f"review-{pr_number}-{session_id[:8]}",
            fn=job_fn,
            on_error=on_error_fn,
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

    @staticmethod
    def _format_feature_result(result: dict) -> str:
        tasks = result.get("tasks", [])
        succeeded = sum(1 for t in tasks if t.get("success"))
        failed = len(tasks) - succeeded

        lines = [f"**Feature complete** (session `{result.get('session_id', '?')[:8]}`)"]
        lines.append(f"Tasks: {succeeded} succeeded, {failed} failed")
        for t in tasks:
            icon = "+" if t.get("success") else "-"
            pr = t.get("pr_url", "")
            reason = t.get("reason", "")
            detail = pr or reason or ""
            lines.append(f"  {icon} `{t.get('task_id', '?')}` {detail}")
        return "\n".join(lines)

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
