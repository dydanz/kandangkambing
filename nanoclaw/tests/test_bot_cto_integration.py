"""Integration tests for CTO Agent routing in bot._handle_message."""
import json
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from agents.cto_agent import CTODecision
from config.settings import Settings

from tests.conftest import SAMPLE_SETTINGS


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
    message.mentions = [MagicMock(id=999)]
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.send = AsyncMock()
    message.create_thread = AsyncMock(return_value=MagicMock(
        id=12345,
        send=AsyncMock(),
    ))
    return message


def _load_settings():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(SAMPLE_SETTINGS, f)
        fname = f.name
    return Settings.load(fname)


@pytest.mark.asyncio
async def test_handle_message_execute_routes_to_orchestrator():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        execute_decision = make_decision("execute", command="feature fix login bug")
        bot.cto.process = AsyncMock(return_value=execute_decision)
        bot.orchestrator.handle = AsyncMock(return_value="Queued feature request.")

        message = make_message("fix the login bug")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_called_once()
        assert bot.orchestrator.handle.call_args.kwargs["command"] == "feature fix login bug"
        assert bot.orchestrator.handle.call_args.kwargs["user_id"] == "123456789"


@pytest.mark.asyncio
async def test_handle_message_respond_posts_directly():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        respond_decision = make_decision(
            "respond",
            response="Auth is slow because of missing indexes.",
            intent="analysis",
        )
        bot.cto.process = AsyncMock(return_value=respond_decision)
        bot.orchestrator.handle = AsyncMock()

        message = make_message("why is auth slow?")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_not_called()
        message.channel.send.assert_called_once_with(
            "Auth is slow because of missing indexes."
        )
        message.create_thread.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_cto_failure_falls_back_to_orchestrator():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        bot.cto.process = AsyncMock(side_effect=Exception("LLM timeout"))
        bot.orchestrator.handle = AsyncMock(return_value="Queued.")

        message = make_message("feature add health check")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_called_once()
        assert bot.orchestrator.handle.call_args.kwargs["command"] == "feature add health check"


@pytest.mark.asyncio
async def test_handle_message_clarify_posts_question():
    from bot import NanoClawBot

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
         patch("bot.CTOAgent"), \
         patch("bot.Auth"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        clarify_decision = make_decision(
            "clarify",
            question="Which part needs improvement — performance, UX, or something specific?",
            intent="unclear",
            confidence=0.2,
        )
        bot.cto.process = AsyncMock(return_value=clarify_decision)
        bot.orchestrator.handle = AsyncMock()

        message = make_message("make it better")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_not_called()
        message.create_thread.assert_not_called()
        message.channel.send.assert_called_once_with(
            "Which part needs improvement — performance, UX, or something specific?"
        )


# --- document action ---

def make_document_decision(
    doc_title="OAuth 2.0 Options",
    doc_filename="oauth-2-options.md",
    save_to_repo=False,
    document_content="# OAuth 2.0 Options\n\n## Summary\nThree flows...",
):
    return CTODecision(
        action="document",
        command=None,
        response=None,
        question=None,
        intent="research",
        confidence=0.9,
        reasoning="brief requested",
        doc_title=doc_title,
        doc_filename=doc_filename,
        save_to_repo=save_to_repo,
        document_content=document_content,
    )


@pytest.mark.asyncio
async def test_handle_message_document_posts_preview():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=False)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()

        message = make_message("research OAuth options")
        await bot._handle_message(message)

        bot.orchestrator.handle.assert_not_called()
        message.channel.send.assert_called_once()
        sent_text = message.channel.send.call_args[0][0]
        assert "OAuth" in sent_text
        message.create_thread.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_document_save_to_repo_calls_git():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=True)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()
        bot.git.write_and_commit = AsyncMock()

        message = make_message("research OAuth options and save it")
        await bot._handle_message(message)

        bot.git.write_and_commit.assert_called_once()
        call_kwargs = bot.git.write_and_commit.call_args.kwargs
        assert call_kwargs["path"] == "docs/research/oauth-2-options.md"
        assert "OAuth" in call_kwargs["content"]
        assert "oauth" in call_kwargs["message"].lower()

        assert message.channel.send.call_count == 2
        second_send = message.channel.send.call_args_list[1][0][0]
        assert "docs/research/oauth-2-options.md" in second_send


@pytest.mark.asyncio
async def test_handle_message_document_git_failure_posts_warning():
    from bot import NanoClawBot

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
         patch("bot.Auth"), \
         patch("bot.CTOAgent"):

        bot = NanoClawBot(_load_settings())
        bot.client.user = MagicMock(id=999)

        doc_decision = make_document_decision(save_to_repo=True)
        bot.cto.process = AsyncMock(return_value=doc_decision)
        bot.orchestrator.handle = AsyncMock()
        bot.git.write_and_commit = AsyncMock(side_effect=Exception("git commit failed"))

        message = make_message("research OAuth options and commit it")
        await bot._handle_message(message)

        assert message.channel.send.call_count == 2
        warning_msg = message.channel.send.call_args_list[1][0][0]
        assert "⚠️" in warning_msg
        assert "repo" in warning_msg.lower()
