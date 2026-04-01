"""NanoClaw Discord Bot — entry point with full message/reaction handling."""
import asyncio
import logging
import os
import sys

import discord

from config.settings import Settings
from memory.shared import SharedMemory
from memory.task_store import TaskStore
from memory.cost_tracker import CostTracker
from memory.context_loader import ContextLoader
from tools.llm_router import LLMRouter
from tools.claude_code import ClaudeCodeTool
from tools.git_tool import GitTool
from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent
from workflow.engine import WorkflowEngine
from workflow.approval_gate import ApprovalGate, APPROVE_EMOJI, REJECT_EMOJI
from workflow.job_queue import JobQueue, Job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nanoclaw")


class NanoClawBot:
    """Discord bot that wires together all NanoClaw components."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._allowed_users = set(settings.discord.allowed_user_ids)

        # Discord client
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        self.client = discord.Client(intents=intents)

        # Infrastructure
        self.memory = SharedMemory()
        self.task_store = TaskStore()
        self.cost_tracker = CostTracker()
        self.context_loader = ContextLoader()
        self.router = LLMRouter(settings)
        self.job_queue = JobQueue(
            max_concurrent=settings.workflow.max_concurrent_jobs,
        )

        # Tools
        self.claude_code = ClaudeCodeTool()
        self.git = GitTool(
            project_path=settings.paths.project_path,
            worktree_base=settings.paths.worktree_base,
            github_repo=settings.paths.github_repo,
        )

        # Agents
        self.pm = PMAgent(self.router, self.memory, self.context_loader)
        self.dev = DevAgent(
            self.router, self.memory, self.context_loader,
            self.claude_code, self.git, self.task_store,
        )
        self.qa = QAAgent(self.router, self.memory, self.context_loader)

        # Approval gate
        self.approval_gate = ApprovalGate(
            self.client,
            timeout_minutes=settings.workflow.approval_timeout_minutes,
        )

        # Workflow engine
        self.engine = WorkflowEngine(
            pm=self.pm, dev=self.dev, qa=self.qa,
            task_store=self.task_store,
            approval_gate=self.approval_gate,
            max_retries=settings.workflow.max_retries,
        )

        # Orchestrator (imported here to avoid circular)
        from orchestrator import Orchestrator
        self.orchestrator = Orchestrator(
            engine=self.engine,
            task_store=self.task_store,
            job_queue=self.job_queue,
            cost_tracker=self.cost_tracker,
        )

        # Register event handlers
        self._register_events()

    def _register_events(self):
        client = self.client

        @client.event
        async def on_ready():
            logger.info("NanoClaw online as %s", client.user)
            asyncio.create_task(self.job_queue.run())

        @client.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)

        @client.event
        async def on_reaction_add(reaction: discord.Reaction,
                                  user: discord.User):
            await self._handle_reaction(reaction, user)

    async def _handle_message(self, message: discord.Message):
        # Ignore own messages
        if message.author == self.client.user:
            return

        # Must mention the bot
        if self.client.user not in message.mentions:
            return

        # Whitelist check — silent ignore for non-allowed users
        if str(message.author.id) not in self._allowed_users:
            logger.info("Ignored message from non-allowed user %s",
                        message.author.id)
            return

        # Strip the mention to get the command text
        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "")
            content = content.replace(f"<@!{mention.id}>", "")
        command = content.strip()

        if not command:
            await message.channel.send("Usage: `@NanoClaw <command>`")
            return

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

        if response:
            await target_channel.send(response)

    async def _handle_reaction(self, reaction: discord.Reaction,
                               user: discord.User):
        # Ignore own reactions
        if user == self.client.user:
            return

        # Only process approve/reject emojis
        emoji = str(reaction.emoji)
        if emoji not in (APPROVE_EMOJI, REJECT_EMOJI):
            return

        # Must be from allowed user
        if str(user.id) not in self._allowed_users:
            return

        # Check if this message is a pending approval
        pending_ids = self.approval_gate.get_pending_task_ids()
        if not pending_ids:
            return

        # Match the reaction to the approval message
        # The approval gate stores the task_id as key — check if the message
        # is from the bot and contains a pending task ID
        msg_content = reaction.message.content
        for task_id in pending_ids:
            if task_id in msg_content:
                approved = emoji == APPROVE_EMOJI
                self.approval_gate.resolve(task_id, approved)
                break

    @staticmethod
    def _is_task_command(command: str) -> bool:
        """Return True if this command will produce task output worth threading."""
        cmd_lower = command.lower()
        return any(cmd_lower.startswith(prefix) for prefix in (
            "pm ", "dev ", "implement ", "build ", "feature ",
        ))

    def run(self):
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            logger.error("DISCORD_BOT_TOKEN not set in environment")
            sys.exit(1)
        self.client.run(token)


def main():
    settings_path = os.environ.get("NANOCLAW_SETTINGS", "config/settings.json")
    try:
        settings = Settings.load(settings_path)
    except Exception as e:
        logger.error("Failed to load settings from %s: %s", settings_path, e)
        sys.exit(1)

    bot = NanoClawBot(settings)
    bot.run()


if __name__ == "__main__":
    main()
