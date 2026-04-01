"""Tests for PR7 — Safety & Control (Auth, RateLimiter, BudgetGuard, DailyScheduler)."""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from safety.auth import Auth
from safety.rate_limiter import RateLimiter
from safety.budget_guard import BudgetGuard
from safety.scheduler import DailyScheduler


# --- Auth ---

def test_auth_allowed():
    auth = Auth(["111", "222"])
    assert auth.is_allowed("111") is True
    assert auth.is_allowed("222") is True


def test_auth_not_allowed():
    auth = Auth(["111"])
    assert auth.is_allowed("999") is False


def test_auth_empty_whitelist():
    auth = Auth([])
    assert auth.is_allowed("111") is False


def test_auth_add_user():
    auth = Auth(["111"])
    auth.add_user("222")
    assert auth.is_allowed("222") is True


def test_auth_remove_user():
    auth = Auth(["111", "222"])
    auth.remove_user("222")
    assert auth.is_allowed("222") is False


def test_auth_remove_nonexistent():
    auth = Auth(["111"])
    auth.remove_user("999")  # should not raise
    assert auth.is_allowed("111") is True


def test_auth_allowed_users_property():
    auth = Auth(["111", "222"])
    assert auth.allowed_users == {"111", "222"}


# --- RateLimiter ---

def test_rate_limiter_allows_under_limit():
    limiter = RateLimiter({"test_per_hour": 3}, cooldown_minutes=5)
    allowed, reason = limiter.check("test")
    assert allowed is True
    assert reason == ""


def test_rate_limiter_blocks_at_limit():
    limiter = RateLimiter({"test_per_hour": 2}, cooldown_minutes=5)
    limiter.record("test")
    limiter.record("test")
    allowed, reason = limiter.check("test")
    assert allowed is False
    assert "Rate limit" in reason


def test_rate_limiter_cooldown():
    limiter = RateLimiter({"test_per_hour": 1}, cooldown_minutes=10)
    limiter.record("test")
    allowed, _ = limiter.check("test")
    assert allowed is False

    # Subsequent check should also fail (cooldown)
    allowed, reason = limiter.check("test")
    assert allowed is False
    assert "cooldown" in reason.lower()


def test_rate_limiter_unknown_operation_allowed():
    limiter = RateLimiter({"known_per_hour": 5})
    allowed, _ = limiter.check("unknown_op")
    assert allowed is True


def test_rate_limiter_record_and_usage():
    limiter = RateLimiter({"test_per_hour": 10})
    limiter.record("test")
    limiter.record("test")
    usage = limiter.get_usage("test")
    assert usage["used"] == 2
    assert usage["limit"] == 10
    assert usage["in_cooldown"] is False


def test_rate_limiter_reset():
    limiter = RateLimiter({"test_per_hour": 1}, cooldown_minutes=5)
    limiter.record("test")
    limiter.check("test")  # triggers cooldown
    limiter.reset("test")
    allowed, _ = limiter.check("test")
    assert allowed is True


def test_rate_limiter_direct_key_match():
    limiter = RateLimiter({"llm_calls_per_hour": 5})
    limiter.record("llm_calls")
    usage = limiter.get_usage("llm_calls")
    assert usage["limit"] == 5


def test_rate_limiter_expired_entries_pruned():
    limiter = RateLimiter({"test_per_hour": 2}, cooldown_minutes=1)
    # Manually inject an old timestamp
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    limiter._windows["test"].append(old_time)
    limiter.record("test")
    # Should have pruned the old one, only 1 recent
    allowed, _ = limiter.check("test")
    assert allowed is True


# --- BudgetGuard ---

@pytest.mark.asyncio
async def test_budget_guard_under_limit():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=1.00)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00, warn_at_percent=0.80)
    allowed, msg = await guard.check()
    assert allowed is True
    assert msg == ""


@pytest.mark.asyncio
async def test_budget_guard_over_limit():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=5.50)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00)
    allowed, msg = await guard.check()
    assert allowed is False
    assert "limit reached" in msg.lower()


@pytest.mark.asyncio
async def test_budget_guard_at_exact_limit():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=5.00)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00)
    allowed, msg = await guard.check()
    assert allowed is False


@pytest.mark.asyncio
async def test_budget_guard_warning_threshold():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=4.10)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00, warn_at_percent=0.80)
    allowed, msg = await guard.check()
    assert allowed is True
    assert "warning" in msg.lower()


@pytest.mark.asyncio
async def test_budget_guard_warning_only_once():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=4.10)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00, warn_at_percent=0.80)

    _, msg1 = await guard.check()
    assert "warning" in msg1.lower()

    _, msg2 = await guard.check()
    assert msg2 == ""  # no second warning


@pytest.mark.asyncio
async def test_budget_guard_reset_warning():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=4.10)
    guard = BudgetGuard(tracker, daily_limit_usd=5.00, warn_at_percent=0.80)

    await guard.check()
    assert guard.is_warning_sent is True

    guard.reset_daily_warning()
    assert guard.is_warning_sent is False

    _, msg = await guard.check()
    assert "warning" in msg.lower()


@pytest.mark.asyncio
async def test_budget_guard_warning_callback():
    tracker = MagicMock()
    tracker.daily_total = AsyncMock(return_value=4.50)
    callback = AsyncMock()
    guard = BudgetGuard(
        tracker, daily_limit_usd=5.00, warn_at_percent=0.80,
        on_warning=callback,
    )
    await guard.check()
    callback.assert_called_once()


# --- DailyScheduler ---

@pytest.mark.asyncio
async def test_scheduler_parses_time():
    callback = AsyncMock()
    sched = DailyScheduler("09:30", callback)
    assert sched.hour == 9
    assert sched.minute == 30


@pytest.mark.asyncio
async def test_scheduler_stop():
    callback = AsyncMock()
    sched = DailyScheduler("00:00", callback)
    await sched.stop()
    assert sched._stop is True


@pytest.mark.asyncio
async def test_scheduler_fires_callback():
    callback = AsyncMock()
    reset_fn = MagicMock()
    sched = DailyScheduler("00:00", callback, on_day_reset=reset_fn)

    # Patch _sleep_until_next to return immediately once, then stop
    call_count = 0

    async def fake_sleep():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            sched._stop = True

    sched._sleep_until_next = fake_sleep

    await sched.run()
    callback.assert_called_once()
    reset_fn.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_handles_callback_error():
    callback = AsyncMock(side_effect=RuntimeError("report failed"))
    sched = DailyScheduler("00:00", callback)

    call_count = 0

    async def fake_sleep():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            sched._stop = True

    sched._sleep_until_next = fake_sleep

    # Should not raise
    await sched.run()
    callback.assert_called_once()


# --- Orchestrator safety integration ---

@pytest.mark.asyncio
async def test_orchestrator_blocks_on_budget():
    from orchestrator import Orchestrator

    engine = MagicMock()
    engine._noop_progress = AsyncMock()
    task_store = MagicMock()
    task_store.get = AsyncMock(return_value={"id": "T1"})
    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock()
    cost_tracker = MagicMock()
    budget_guard = MagicMock()
    budget_guard.check = AsyncMock(return_value=(False, "Budget exceeded"))

    orch = Orchestrator(
        engine=engine, task_store=task_store, job_queue=job_queue,
        cost_tracker=cost_tracker, budget_guard=budget_guard,
    )
    result = await orch.handle("PM define something", "user1")
    assert result == "Budget exceeded"
    job_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_blocks_on_rate_limit():
    from orchestrator import Orchestrator

    engine = MagicMock()
    engine._noop_progress = AsyncMock()
    task_store = MagicMock()
    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock()
    cost_tracker = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.check = MagicMock(return_value=(False, "Rate limited"))
    budget_guard = MagicMock()
    budget_guard.check = AsyncMock(return_value=(True, ""))

    orch = Orchestrator(
        engine=engine, task_store=task_store, job_queue=job_queue,
        cost_tracker=cost_tracker, rate_limiter=rate_limiter,
        budget_guard=budget_guard,
    )
    result = await orch.handle("feature add logging", "user1")
    assert result == "Rate limited"
    job_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_allows_when_safety_passes():
    from orchestrator import Orchestrator

    engine = MagicMock()
    engine._noop_progress = AsyncMock()
    engine.run_feature = AsyncMock()
    task_store = MagicMock()
    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock()
    cost_tracker = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.check = MagicMock(return_value=(True, ""))
    budget_guard = MagicMock()
    budget_guard.check = AsyncMock(return_value=(True, ""))

    orch = Orchestrator(
        engine=engine, task_store=task_store, job_queue=job_queue,
        cost_tracker=cost_tracker, rate_limiter=rate_limiter,
        budget_guard=budget_guard,
    )
    result = await orch.handle("PM define something", "user1")
    assert "Queued" in result
    job_queue.enqueue.assert_called_once()
