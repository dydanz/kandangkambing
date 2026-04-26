"""NanoClaw Discord Bot — entry point with full message/reaction handling."""
import asyncio
import logging
import uuid
import os
import subprocess
import sys

import discord
import openai

from config.settings import Settings
from memory.shared import SharedMemory
from memory.task_store import TaskStore
from memory.cost_tracker import CostTracker
from memory.context_loader import ContextLoader
from tools.llm_router import LLMRouter
from tools.claude_code import ClaudeCodeTool, VerificationLayer
from tools.git_tool import GitTool
from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent
from agents.cto_agent import CTOAgent
from workflow.engine import WorkflowEngine
from workflow.approval_gate import ApprovalGate, APPROVE_EMOJI, REJECT_EMOJI
from workflow.job_queue import JobQueue, Job
from safety.auth import Auth
from safety.rate_limiter import RateLimiter
from safety.budget_guard import BudgetGuard
from safety.scheduler import DailyScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nanoclaw")


class NanoClawBot:
    """Discord bot that wires together all NanoClaw components."""

    def __init__(self, settings: Settings):
        self.settings = settings

        # Discord client
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        self.client = discord.Client(intents=intents)

        # Safety
        self.auth = Auth(settings.discord.allowed_user_ids)
        self.rate_limiter = RateLimiter(
            limits={
                "llm_calls_per_hour": settings.rate_limits.llm_calls_per_hour,
                "claude_code_per_hour": settings.rate_limits.claude_code_per_hour,
                "git_pushes_per_hour": settings.rate_limits.git_pushes_per_hour,
            },
            cooldown_minutes=settings.rate_limits.cooldown_minutes,
        )

        # Infrastructure
        self.memory = SharedMemory()
        self.task_store = TaskStore()
        self.cost_tracker = CostTracker()
        self.context_loader = ContextLoader()
        self.router = LLMRouter(self.cost_tracker, settings)
        self.job_queue = JobQueue(
            max_concurrent=settings.workflow.max_concurrent_jobs,
        )

        # Tools
        self.claude_code = ClaudeCodeTool(VerificationLayer())
        self.git = GitTool(
            repo_path=settings.paths.project_path,
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
        self.cto = CTOAgent(self.router, self.memory, self.context_loader)

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

        # Budget guard
        self.budget_guard = BudgetGuard(
            cost_tracker=self.cost_tracker,
            daily_limit_usd=settings.budget.daily_limit_usd,
            warn_at_percent=settings.budget.warn_at_percent,
        )

        # Orchestrator (imported here to avoid circular)
        from orchestrator import Orchestrator
        self.orchestrator = Orchestrator(
            engine=self.engine,
            task_store=self.task_store,
            job_queue=self.job_queue,
            cost_tracker=self.cost_tracker,
            rate_limiter=self.rate_limiter,
            budget_guard=self.budget_guard,
        )

        # Daily scheduler
        self.scheduler = DailyScheduler(
            report_time=settings.budget.daily_report_time,
            callback=self._post_daily_report,
            on_day_reset=self.budget_guard.reset_daily_warning,
        )

        # Register event handlers
        self._register_events()

    async def _startup_checks(self) -> None:
        """Run API health checks and post results to log channel."""
        channel = self.client.get_channel(int(self.settings.discord.log_channel_id))
        results = ["**NanoClaw startup health check**"]

        # Discord — already online if we're here
        results.append("Discord ✅ connected as `{}`".format(self.client.user))

        # OpenAI
        try:
            oai = openai.AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            await oai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            results.append("OpenAI ✅ key valid")
        except Exception as e:
            results.append(f"OpenAI ❌ {e}")

        # Google
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import google.generativeai as genai
                genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
                model = genai.GenerativeModel("gemini-2.5-flash")
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: model.generate_content("ping")
                )
            results.append("Google ✅ key valid")
        except Exception as e:
            results.append(f"Google ❌ {str(e)[:200]}")

        # GitHub
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "auth", "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                results.append("GitHub ✅ token valid")
            else:
                results.append(f"GitHub ❌ {stdout.decode().strip()[:200]}")
        except Exception as e:
            results.append(f"GitHub ❌ {e}")

        # Anthropic
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key and not anthropic_key.startswith("your_"):
            results.append("Anthropic ✅ key present (not tested)")
        else:
            results.append("Anthropic ⚠️ key not set — Claude Code tool will be unavailable")

        msg = "\n".join(results)
        logger.info(msg)
        if channel:
            # Discord limit is 2000 chars; truncate if needed
            if len(msg) > 1900:
                msg = msg[:1900] + "\n…(truncated)"
            await channel.send(msg)
        else:
            logger.warning("Log channel not found — check log_channel_id in settings")

    def _register_events(self):
        client = self.client

        @client.event
        async def on_ready():
            logger.info("NanoClaw online as %s", client.user)
            asyncio.create_task(self.job_queue.run())
            asyncio.create_task(self.scheduler.run())
            asyncio.create_task(self._startup_checks())

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
        bot_id = self.client.user.id if self.client.user else None
        if bot_id is None or not any(m.id == bot_id for m in message.mentions):
            return

        # Whitelist check — silent ignore for non-allowed users
        if not self.auth.is_allowed(str(message.author.id)):
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

        # Run CTO Agent intent classification
        session_id = None
        decision = None
        try:
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
        if not self.auth.is_allowed(str(user.id)):
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

    async def _post_daily_report(self) -> None:
        """Post daily cost/task report to the log channel."""
        channel_id = self.settings.discord.log_channel_id
        channel = self.client.get_channel(int(channel_id))
        if not channel:
            logger.warning("Log channel %s not found for daily report", channel_id)
            return

        daily_cost = await self.cost_tracker.daily_total()
        tasks = await self.task_store.list_tasks()
        done = sum(1 for t in tasks if t.get("status") == "done")
        failed = sum(1 for t in tasks if t.get("status") == "failed")

        report = (
            f"**NanoClaw Daily Report**\n"
            f"Tasks completed: {done} | Failed: {failed}\n"
            f"LLM cost today: ${daily_cost:.2f} / "
            f"${self.settings.budget.daily_limit_usd:.2f} limit"
        )
        await channel.send(report)

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
