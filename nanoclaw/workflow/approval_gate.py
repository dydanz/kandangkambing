"""ApprovalGate — Discord reaction-based approval for task pushes."""
import asyncio
import logging
from typing import Optional

import discord

from agents.dev import DevResult

logger = logging.getLogger("nanoclaw.approval_gate")

APPROVE_EMOJI = "\u2705"  # ✅
REJECT_EMOJI = "\u274c"   # ❌


class ApprovalGate:
    def __init__(self, bot: discord.Client,
                 timeout_minutes: int = 60):
        self.bot = bot
        self.timeout = timeout_minutes * 60
        self._pending: dict[str, asyncio.Future] = {}

    async def request(self, task: dict, dev_result: DevResult) -> bool:
        """
        Post approval message to Discord thread.
        Waits for reaction from allowed user.
        Returns True if approved, False if rejected or timed out.
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
        files_list = "\n".join(f"  - `{f}`" for f in dev_result.files_changed[:20])
        msg_text = (
            f"**Task {task['id']}** ready for review\n\n"
            f"**Branch:** `{dev_result.branch}`\n"
            f"**Files changed ({len(dev_result.files_changed)}):**\n{files_list}\n\n"
            f"React {APPROVE_EMOJI} to approve and push, "
            f"or {REJECT_EMOJI} to reject."
        )

        msg = await channel.send(msg_text)
        await msg.add_reaction(APPROVE_EMOJI)
        await msg.add_reaction(REJECT_EMOJI)

        # Create future and wait
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[task["id"]] = future

        try:
            approved = await asyncio.wait_for(future, timeout=self.timeout)
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

    def resolve(self, task_id: str, approved: bool) -> None:
        """Called by bot's on_reaction_add — resolves the pending future."""
        future = self._pending.get(task_id)
        if future and not future.done():
            future.set_result(approved)
            logger.info("Task %s %s", task_id,
                         "approved" if approved else "rejected")

    def get_pending_task_ids(self) -> list[str]:
        """Return list of task IDs currently awaiting approval."""
        return list(self._pending.keys())
