"""Tests for memory layer — TaskStore, SharedMemory, CostTracker, ContextLoader (PR2)."""
import asyncio
import json
import os

import pytest

from memory.task_store import TaskStore
from memory.shared import SharedMemory
from memory.cost_tracker import CostTracker
from memory.context_loader import ContextLoader


# --- TaskStore ---

@pytest.fixture
def task_store(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": []}))
    return TaskStore(str(path))


@pytest.mark.asyncio
async def test_task_create_persists(task_store):
    task = await task_store.create("Add endpoint", "GET /health returning 200")
    assert task["id"] == "TASK-001"
    assert task["title"] == "Add endpoint"
    assert task["status"] == "open"
    assert task["retry_count"] == 0

    # Verify persisted to file
    reloaded = await task_store.get("TASK-001")
    assert reloaded["title"] == "Add endpoint"


@pytest.mark.asyncio
async def test_task_create_increments_ids(task_store):
    t1 = await task_store.create("First", "desc")
    t2 = await task_store.create("Second", "desc")
    assert t1["id"] == "TASK-001"
    assert t2["id"] == "TASK-002"


@pytest.mark.asyncio
async def test_task_update(task_store):
    await task_store.create("Task", "desc")
    updated = await task_store.update("TASK-001", status="in_progress")
    assert updated["status"] == "in_progress"


@pytest.mark.asyncio
async def test_task_update_not_found(task_store):
    with pytest.raises(KeyError):
        await task_store.update("TASK-999", status="done")


@pytest.mark.asyncio
async def test_task_list_filter(task_store):
    await task_store.create("A", "desc")
    await task_store.create("B", "desc")
    await task_store.update("TASK-001", status="done")
    open_tasks = await task_store.list_tasks(status="open")
    assert len(open_tasks) == 1
    assert open_tasks[0]["id"] == "TASK-002"


@pytest.mark.asyncio
async def test_task_get_ready_respects_deps(task_store):
    await task_store.create("A", "desc", dependencies=[])
    await task_store.create("B", "desc", dependencies=["TASK-001"])
    ready = await task_store.get_ready()
    assert len(ready) == 1
    assert ready[0]["id"] == "TASK-001"

    # Mark A done, B should now be ready
    await task_store.update("TASK-001", status="done")
    ready2 = await task_store.get_ready()
    assert len(ready2) == 1
    assert ready2[0]["id"] == "TASK-002"


@pytest.mark.asyncio
async def test_task_get_ready_priority_order(task_store):
    await task_store.create("Low", "desc", priority="low")
    await task_store.create("High", "desc", priority="high")
    await task_store.create("Med", "desc", priority="medium")
    ready = await task_store.get_ready()
    assert [t["priority"] for t in ready] == ["high", "medium", "low"]


@pytest.mark.asyncio
async def test_task_increment_retry(task_store):
    await task_store.create("Task", "desc")
    count = await task_store.increment_retry("TASK-001")
    assert count == 1
    count2 = await task_store.increment_retry("TASK-001")
    assert count2 == 2


@pytest.mark.asyncio
async def test_task_increment_retry_not_found(task_store):
    with pytest.raises(KeyError):
        await task_store.increment_retry("TASK-999")


# --- SharedMemory ---

@pytest.fixture
def shared_memory(tmp_path):
    return SharedMemory(str(tmp_path / "conversations.db"))


@pytest.mark.asyncio
async def test_shared_memory_roundtrip(shared_memory):
    await shared_memory.save_message(
        role="dev", agent="dev", content="Hello world",
        task_id="TASK-001", model="claude-sonnet-4-6",
        tokens_in=100, tokens_out=50, cost_usd=0.001,
    )
    messages = await shared_memory.get_recent(limit=10, task_id="TASK-001")
    assert len(messages) == 1
    assert messages[0]["role"] == "dev"
    assert messages[0]["content"] == "Hello world"
    assert messages[0]["agent"] == "dev"
    assert "timestamp" in messages[0]


@pytest.mark.asyncio
async def test_shared_memory_filter_by_task(shared_memory):
    await shared_memory.save_message(role="dev", agent="dev",
                                      content="Task 1 msg", task_id="TASK-001")
    await shared_memory.save_message(role="qa", agent="qa",
                                      content="Task 2 msg", task_id="TASK-002")
    msgs = await shared_memory.get_recent(limit=10, task_id="TASK-001")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Task 1 msg"


@pytest.mark.asyncio
async def test_shared_memory_limit(shared_memory):
    for i in range(5):
        await shared_memory.save_message(
            role="dev", agent="dev", content=f"msg {i}")
    msgs = await shared_memory.get_recent(limit=3)
    assert len(msgs) == 3
    # Should be the 3 most recent, in chronological order
    assert msgs[0]["content"] == "msg 2"
    assert msgs[2]["content"] == "msg 4"


@pytest.mark.asyncio
async def test_shared_memory_empty(shared_memory):
    msgs = await shared_memory.get_recent(limit=10)
    assert msgs == []


# --- CostTracker ---

@pytest.fixture
def cost_tracker(tmp_path):
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text(json.dumps({
        "anthropic": {
            "claude-sonnet-4-6": {"in": 3.0, "out": 15.0}
        },
        "openai": {
            "gpt-4o": {"in": 2.5, "out": 10.0}
        },
    }))
    return CostTracker(
        db_path=str(tmp_path / "costs.db"),
        pricing_path=str(pricing_path),
    )


@pytest.mark.asyncio
async def test_cost_log_calculates_cost(cost_tracker):
    cost = await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="dev",
        provider="anthropic", model="claude-sonnet-4-6",
        tokens_in=1000, tokens_out=500,
    )
    # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
    assert abs(cost - 0.0105) < 0.0001


@pytest.mark.asyncio
async def test_cost_daily_total_empty(cost_tracker):
    total = await cost_tracker.daily_total()
    assert total == 0.0


@pytest.mark.asyncio
async def test_cost_daily_total_after_log(cost_tracker):
    await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="dev",
        provider="anthropic", model="claude-sonnet-4-6",
        tokens_in=1000, tokens_out=500,
    )
    await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="qa",
        provider="openai", model="gpt-4o",
        tokens_in=2000, tokens_out=1000,
    )
    total = await cost_tracker.daily_total()
    # 0.0105 + (2000*2.5/1M + 1000*10.0/1M) = 0.0105 + 0.005 + 0.01 = 0.0255
    assert abs(total - 0.0255) < 0.0001


@pytest.mark.asyncio
async def test_cost_task_total(cost_tracker):
    await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="dev",
        provider="anthropic", model="claude-sonnet-4-6",
        tokens_in=1000, tokens_out=500,
    )
    await cost_tracker.log(
        session_id="s1", task_id="TASK-002", agent="dev",
        provider="anthropic", model="claude-sonnet-4-6",
        tokens_in=1000, tokens_out=500,
    )
    t1 = await cost_tracker.task_total("TASK-001")
    assert abs(t1 - 0.0105) < 0.0001
    t2 = await cost_tracker.task_total("TASK-002")
    assert abs(t2 - 0.0105) < 0.0001


@pytest.mark.asyncio
async def test_cost_session_summary(cost_tracker):
    await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="dev",
        provider="anthropic", model="claude-sonnet-4-6",
        tokens_in=1000, tokens_out=500,
    )
    summary = await cost_tracker.session_summary("s1")
    assert summary["session_id"] == "s1"
    assert len(summary["models"]) == 1
    assert summary["models"][0]["provider"] == "anthropic"
    assert summary["total_cost"] > 0


@pytest.mark.asyncio
async def test_cost_unknown_model_returns_zero(cost_tracker):
    cost = await cost_tracker.log(
        session_id="s1", task_id="TASK-001", agent="dev",
        provider="unknown", model="unknown-model",
        tokens_in=1000, tokens_out=500,
    )
    assert cost == 0.0


# --- ContextLoader ---

@pytest.fixture
def context_loader(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "project_overview.md").write_text("# My Project\nA test project.")
    (ctx_dir / "conventions.md").write_text("# Conventions\nUse snake_case.")
    return ContextLoader(str(ctx_dir))


@pytest.mark.asyncio
async def test_context_load_all(context_loader):
    result = await context_loader.load_all()
    assert "My Project" in result
    assert "snake_case" in result
    # Files should be separated
    assert "---" in result


@pytest.mark.asyncio
async def test_context_load_single(context_loader):
    result = await context_loader.load("conventions.md")
    assert "snake_case" in result


@pytest.mark.asyncio
async def test_context_load_missing(context_loader):
    result = await context_loader.load("nonexistent.md")
    assert result == ""


@pytest.mark.asyncio
async def test_context_load_all_empty_dir(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    loader = ContextLoader(str(empty_dir))
    result = await loader.load_all()
    assert result == ""


@pytest.mark.asyncio
async def test_context_load_all_missing_dir(tmp_path):
    loader = ContextLoader(str(tmp_path / "nonexistent"))
    result = await loader.load_all()
    assert result == ""
