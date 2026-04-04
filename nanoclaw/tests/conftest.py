"""Shared test fixtures for NanoClaw."""
import copy
import json
import os
import tempfile

import pytest


SAMPLE_SETTINGS = {
    "discord": {
        "allowed_user_ids": ["123456789"],
        "command_channel_id": "111111",
        "log_channel_id": "222222",
        "commits_channel_id": "333333",
    },
    "workflow": {
        "max_retries": 2,
        "approval_timeout_minutes": 60,
        "job_timeout_minutes": 10,
        "max_concurrent_jobs": 2,
    },
    "rate_limits": {
        "llm_calls_per_hour": 30,
        "claude_code_per_hour": 10,
        "git_pushes_per_hour": 5,
        "cooldown_minutes": 10,
    },
    "budget": {
        "daily_limit_usd": 5.00,
        "warn_at_percent": 0.80,
        "daily_report_time": "09:00",
    },
    "llm": {
        "routing": {
            "coding": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "review": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "spec": {"provider": "openai", "model": "gpt-4o"},
            "simple": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
            "test": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "summarise": {"provider": "google", "model": "gemini-2.0-flash"},
        },
        "fallback_chain": [
            ["anthropic", "claude-sonnet-4-6"],
            ["openai", "gpt-4o"],
            ["google", "gemini-2.0-pro"],
            ["anthropic", "claude-haiku-4-5-20251001"],
        ],
    },
    "paths": {
        "project_path": "/tmp/test-project",
        "worktree_base": "/tmp/test-worktrees",
        "github_repo": "test/test-repo",
    },
}


@pytest.fixture
def settings_path(tmp_path):
    """Write sample settings to a temp file and return its path."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(SAMPLE_SETTINGS))
    return str(path)


@pytest.fixture
def sample_settings():
    """Return the raw settings dict for direct manipulation in tests."""
    return copy.deepcopy(SAMPLE_SETTINGS)
