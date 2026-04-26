"""Tests for CTOAgent — decision parsing, process(), and bot integration."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.cto_agent import CTOAgent, CTODecision
from tools.providers.base import LLMResponse


# --- CTODecision parsing ---

def test_parse_decision_valid_execute():
    raw = json.dumps({
        "action": "execute",
        "command": "feature fix login bug",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "user wants to fix a bug"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "execute"
    assert decision.command == "feature fix login bug"
    assert decision.intent == "coding"
    assert decision.confidence == 0.9


def test_parse_decision_valid_respond():
    raw = json.dumps({
        "action": "respond",
        "command": None,
        "response": "Auth is slow because of N+1 queries in the user lookup.",
        "question": None,
        "intent": "analysis",
        "confidence": 0.85,
        "reasoning": "analysis question"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "respond"
    assert "N+1" in decision.response
    assert decision.command is None


def test_parse_decision_valid_clarify():
    raw = json.dumps({
        "action": "clarify",
        "command": None,
        "response": None,
        "question": "Can you describe what's behaving unexpectedly?",
        "intent": "unclear",
        "confidence": 0.3,
        "reasoning": "too vague"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
    assert decision.question == "Can you describe what's behaving unexpectedly?"


def test_parse_decision_malformed_json_returns_clarify_fallback():
    raw = "Sorry, I can't help with that."
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"
    assert decision.question is not None
    assert len(decision.question) > 0


def test_parse_decision_json_with_prose_wrapper():
    raw = 'Here is my analysis:\n' + json.dumps({
        "action": "execute",
        "command": "status",
        "response": None,
        "question": None,
        "intent": "system",
        "confidence": 0.95,
        "reasoning": "status check"
    }) + '\nEnd.'
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "execute"
    assert decision.command == "status"


def test_parse_decision_missing_fields_returns_clarify_fallback():
    raw = json.dumps({"action": "execute"})
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"


def test_parse_decision_unknown_action_returns_clarify_fallback():
    raw = json.dumps({
        "action": "run_it",
        "command": "some command",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "unknown action"
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"


# --- Shared mock helpers for process() tests ---


def make_router(response_content="{}"):
    router = MagicMock()
    router.route = AsyncMock(return_value=LLMResponse(
        content=response_content,
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
        tokens_in=50,
        tokens_out=30,
        cost_usd=0.0001,
    ))
    return router


def make_memory():
    memory = MagicMock()
    memory.get_recent = AsyncMock(return_value=[])
    memory.save_message = AsyncMock()
    return memory


def make_context():
    context = MagicMock()
    context.load_all = AsyncMock(return_value="# Project context")
    return context


def make_cto_agent(llm_response: str) -> CTOAgent:
    return CTOAgent(make_router(llm_response), make_memory(), make_context())


# --- process() tests ---

@pytest.mark.asyncio
async def test_process_returns_execute_decision():
    llm_json = json.dumps({
        "action": "execute",
        "command": "feature fix login bug",
        "response": None,
        "question": None,
        "intent": "coding",
        "confidence": 0.9,
        "reasoning": "bug fix"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("fix the login bug", session_id="s1")
    assert decision.action == "execute"
    assert decision.command == "feature fix login bug"


@pytest.mark.asyncio
async def test_process_returns_respond_decision():
    llm_json = json.dumps({
        "action": "respond",
        "command": None,
        "response": "Auth is slow due to missing indexes.",
        "question": None,
        "intent": "analysis",
        "confidence": 0.88,
        "reasoning": "analysis"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("why is auth slow?", session_id="s1")
    assert decision.action == "respond"
    assert "indexes" in decision.response


@pytest.mark.asyncio
async def test_process_uses_session_id():
    llm_json = json.dumps({
        "action": "execute", "command": "status",
        "response": None, "question": None,
        "intent": "system", "confidence": 0.95, "reasoning": "status"
    })
    agent = make_cto_agent(llm_json)
    await agent.process("how are we doing?", session_id="thread-abc")
    call_kwargs = agent.router.route.call_args.kwargs
    assert call_kwargs["session_id"] == "thread-abc"


# --- Destructive command guard tests ---

@pytest.mark.asyncio
async def test_destructive_stop_command_is_downgraded_to_clarify():
    llm_json = json.dumps({
        "action": "execute", "command": "STOP",
        "response": None, "question": None,
        "intent": "system", "confidence": 0.9, "reasoning": "stop queue"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("stop everything", session_id="s1")
    assert decision.action == "clarify"
    assert decision.question is not None


@pytest.mark.asyncio
async def test_destructive_delete_command_is_downgraded_to_clarify():
    llm_json = json.dumps({
        "action": "execute", "command": "feature delete all tasks",
        "response": None, "question": None,
        "intent": "coding", "confidence": 0.8, "reasoning": "delete"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("delete everything", session_id="s1")
    assert decision.action == "clarify"


@pytest.mark.asyncio
async def test_non_destructive_command_passes_through():
    llm_json = json.dumps({
        "action": "execute", "command": "feature add health endpoint",
        "response": None, "question": None,
        "intent": "coding", "confidence": 0.9, "reasoning": "add feature"
    })
    agent = make_cto_agent(llm_json)
    decision = await agent.process("add a health endpoint", session_id="s1")
    assert decision.action == "execute"
    assert decision.command == "feature add health endpoint"


@pytest.mark.asyncio
async def test_process_fallback_on_llm_failure():
    agent = CTOAgent(make_router(), make_memory(), make_context())
    agent.router.route = AsyncMock(side_effect=Exception("LLM timeout"))
    decision = await agent.process("do something", session_id="s1")
    assert decision.action == "clarify"


def test_settings_has_research_route(settings_path):
    from config.settings import Settings
    s = Settings.load(settings_path)
    assert "research" in s.llm.routing
    assert s.llm.routing["research"].model == "claude-sonnet-4-6"


# --- document action parsing ---

def test_parse_decision_document_action():
    raw = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "technical brief requested",
        "doc_title": "OAuth 2.0 Options — Technical Brief",
        "doc_filename": "oauth-2-options.md",
        "save_to_repo": True,
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "document"
    assert decision.doc_title == "OAuth 2.0 Options — Technical Brief"
    assert decision.doc_filename == "oauth-2-options.md"
    assert decision.save_to_repo is True
    assert decision.document_content is None


def test_parse_decision_document_missing_doc_fields_returns_clarify():
    raw = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "missing doc fields",
    })
    decision = CTOAgent._parse_decision(raw)
    assert decision.action == "clarify"


# --- research() method ---

@pytest.mark.asyncio
async def test_research_returns_markdown_string():
    markdown_doc = "# OAuth 2.0 Options\n\n## Summary\nThree flows are relevant..."
    agent = make_cto_agent(markdown_doc)
    agent.router.route = AsyncMock(return_value=LLMResponse(
        content=markdown_doc,
        model="claude-sonnet-4-6",
        provider="anthropic",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.001,
    ))
    result = await agent.research(
        topic="research OAuth options",
        doc_title="OAuth 2.0 Options — Technical Brief",
        session_id="s1",
    )
    assert result == markdown_doc
    call_kwargs = agent.router.route.call_args.kwargs
    assert call_kwargs["task_type"] == "research"


@pytest.mark.asyncio
async def test_research_saves_to_memory():
    markdown_doc = "# Test Doc\n\n## Summary\nContent here."
    agent = make_cto_agent(markdown_doc)
    agent.router.route = AsyncMock(return_value=LLMResponse(
        content=markdown_doc,
        model="claude-sonnet-4-6",
        provider="anthropic",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.001,
    ))
    await agent.research("document auth architecture", "Auth Architecture", "s1")
    agent.memory.save_message.assert_called_once()


# --- process() document path ---

@pytest.mark.asyncio
async def test_process_document_calls_research_and_populates_content():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "brief requested",
        "doc_title": "OAuth 2.0 Options — Technical Brief",
        "doc_filename": "oauth-2-options.md",
        "save_to_repo": True,
    })
    agent = make_cto_agent(doc_json)
    markdown_doc = "# OAuth 2.0 Options\n\n## Summary\nThree flows..."

    agent.router.route = AsyncMock(side_effect=[
        LLMResponse(content=doc_json, model="claude-haiku-4-5-20251001",
                    provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001),
        LLMResponse(content=markdown_doc, model="claude-sonnet-4-6",
                    provider="anthropic", tokens_in=100, tokens_out=200, cost_usd=0.001),
    ])

    decision = await agent.process("research OAuth options for PMO", session_id="s1")

    assert decision.action == "document"
    assert decision.document_content == markdown_doc
    assert decision.doc_title == "OAuth 2.0 Options — Technical Brief"
    assert decision.save_to_repo is True


@pytest.mark.asyncio
async def test_process_document_research_failure_returns_clarify():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.9,
        "reasoning": "brief requested",
        "doc_title": "OAuth 2.0 Options",
        "doc_filename": "oauth.md",
        "save_to_repo": False,
    })
    agent = make_cto_agent(doc_json)

    classify_response = LLMResponse(
        content=doc_json, model="claude-haiku-4-5-20251001",
        provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001,
    )
    agent.router.route = AsyncMock(side_effect=[
        classify_response,
        Exception("Sonnet unavailable"),
    ])

    decision = await agent.process("document auth module", session_id="s1")

    assert decision.action == "clarify"
    assert "couldn't generate" in decision.question.lower()


@pytest.mark.asyncio
async def test_process_document_save_to_repo_false():
    doc_json = json.dumps({
        "action": "document",
        "command": None,
        "response": None,
        "question": None,
        "intent": "research",
        "confidence": 0.85,
        "reasoning": "architecture doc",
        "doc_title": "Auth Module Architecture",
        "doc_filename": "auth-architecture.md",
        "save_to_repo": False,
    })
    agent = make_cto_agent(doc_json)
    agent.router.route = AsyncMock(side_effect=[
        LLMResponse(content=doc_json, model="claude-haiku-4-5-20251001",
                    provider="anthropic", tokens_in=50, tokens_out=30, cost_usd=0.0001),
        LLMResponse(content="# Auth Architecture\n\n## Summary\n...",
                    model="claude-sonnet-4-6", provider="anthropic",
                    tokens_in=100, tokens_out=200, cost_usd=0.001),
    ])

    decision = await agent.process("document auth module architecture", session_id="s1")

    assert decision.action == "document"
    assert decision.save_to_repo is False
    assert decision.document_content is not None
