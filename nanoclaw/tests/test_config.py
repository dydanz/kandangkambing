"""Tests for config/settings.py — Settings validation (PR1)."""
import json

import pytest
from pydantic import ValidationError

from config.settings import Settings


def test_load_valid_settings(settings_path):
    """Settings.load() succeeds with a complete config file."""
    settings = Settings.load(settings_path)
    assert settings.discord.allowed_user_ids == ["123456789"]
    assert settings.workflow.max_retries == 2
    assert settings.budget.daily_limit_usd == 5.00
    assert settings.llm.routing["coding"].provider == "anthropic"
    assert settings.paths.github_repo == "test/test-repo"


def test_load_missing_required_field_raises(tmp_path):
    """Missing required field raises ValidationError."""
    incomplete = {"workflow": {"max_retries": 2}}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(incomplete))
    with pytest.raises(ValidationError):
        Settings.load(str(path))


def test_load_missing_discord_user_ids_raises(tmp_path, sample_settings):
    """Missing allowed_user_ids in discord section raises ValidationError."""
    del sample_settings["discord"]["allowed_user_ids"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(sample_settings))
    with pytest.raises(ValidationError):
        Settings.load(str(path))


def test_load_nonexistent_file_raises():
    """Loading from a path that doesn't exist raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        Settings.load("/tmp/nonexistent_nanoclaw_settings.json")


def test_defaults_applied(settings_path):
    """Default values are applied for optional fields."""
    settings = Settings.load(settings_path)
    assert settings.workflow.approval_timeout_minutes == 60
    assert settings.rate_limits.cooldown_minutes == 10
    assert settings.budget.warn_at_percent == 0.80


def test_fallback_chain_structure(settings_path):
    """Fallback chain is a list of [provider, model] pairs."""
    settings = Settings.load(settings_path)
    for entry in settings.llm.fallback_chain:
        assert len(entry) == 2
        assert isinstance(entry[0], str)
        assert isinstance(entry[1], str)


def test_llm_routing_keys(settings_path):
    """All expected routing keys are present."""
    settings = Settings.load(settings_path)
    expected_keys = {"coding", "review", "spec", "simple", "test", "summarise", "cto", "research"}
    assert set(settings.llm.routing.keys()) == expected_keys
