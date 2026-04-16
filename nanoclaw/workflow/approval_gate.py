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
                github_task = asyncio.create_task(
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
                winner = next(iter(done))
                try:
                    return winner.result()
                except Exception as exc:
                    logger.warning("ApprovalGate signal raised %s — treating as rejected", exc)
                    return False
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
        """Poll GitHub PR state. Returns True on MERGED, False on CLOSED.
        Retries on transient API errors."""
        while True:
            try:
                state = await self.git.get_pr_state(pr_number)
            except Exception as exc:
                logger.warning("Error polling PR #%d state: %s — retrying",
                               pr_number, exc)
                await asyncio.sleep(poll_interval_seconds)
                continue
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
