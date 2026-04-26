"""Integration tests for CTO Agent routing in bot._handle_message."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import discord

from agents.cto_agent import CTODecision


def make_decision(action, command=None, response=None, question=None,
                  intent="coding", confidence=0.9):
    return CTODecision(
        action=action, command=command, response=response,
        question=question, intent=intent,
        confidence=confidence, reasoning="test"
    )


def make_message(content="fix the login bug", author_id="123456789"):
    message = MagicMock(spec=discord.Message)
    message.content = f"<@999> {content}"
    message.author = MagicMock()
    message.author.id = int(author_id)
    message.author.__eq__ = lambda self, other: False
    message.mentions = [MagicMock(id=999)]
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.send = AsyncMock()
    message.create_thread = AsyncMock(return_value=MagicMock(
        id=12345,
        send=AsyncMock(),
    ))
    return message


@pytest.mark.asyncio
async def test_handle_message_execute_routes_to_orchestrator():
    from bot import NanoClawBot
    from config.settings import Settings
    import json, tempfile

    settings_dict = {
        "discord": {"allowed_user_ids": ["123456789"],
                    "command_channel_id": "1", "log_channel_id": "2",
                    "commits_channel_id": "3"},
        "workflow": {"max_retries": 2, "approval_timeout_minutes": 60,
                     "job_timeout_minutes": 10, "max_concurrent_jobs": 2},
        "rate_limits": {"llm_calls_per_hour": 30, "claude_code_per_hour": 10,
                        "git_pushes_per_hour": 5, "cooldown_minutes": 10},
        "budget": {"daily_limit_usd": 5.0, "warn_at_percent": 0.8,
                   "daily_report_time": "09:00"},
        "llm": {
            "routing": {
                "coding": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "review": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "spec": {"provider": "openai", "model": "gpt-4o"},
                "simple": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
                "test": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                "summarise": {"provider": "google", "model": "gemini-2.0-flash"},
                "cto": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
            },
            "fallback_chain": [["anthropic", "claude-sonnet-4-6"]]
        },
        "paths": {"project_path": "/tmp/p", "worktree_base": "/tmp/w",
                  "github_repo": "test/repo"}
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(settings_dict, f)
        settings_path = f.name

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
         patch("bot.CTOAgent") as MockCTO:

        settings = Settings.load(settings_path)
        bot = NanoClawBot(settings)

        execute_decision = make_decision("execute", command="feature fix login bug")
        bot.cto.process = AsyncMock(return_value=execute_decision)
        bot.orchestrator.handle = AsyncMock(return_value="Queued feature request.")
        bot.client.user = MagicMock(id=999)

        message = make_message("fix the login bug")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_called_once()
        call_args = bot.orchestrator.handle.call_args
        assert call_args.kwargs["command"] == "feature fix login bug"


@pytest.mark.asyncio
async def test_handle_message_respond_posts_directly():
    pass  # stub — Task 6 fills this in


@pytest.mark.asyncio
async def test_handle_message_cto_failure_falls_back_to_orchestrator(tmp_path):
    pass  # stub — Task 6 fills this in
