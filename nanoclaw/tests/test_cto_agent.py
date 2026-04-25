"""Tests for CTOAgent — decision parsing, process(), and bot integration."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.cto_agent import CTOAgent, CTODecision


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
