"""Tests for PR6 — WorkflowEngine, JobQueue, ApprovalGate, Orchestrator."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.dev import DevResult, PRInfo
from workflow.engine import WorkflowEngine, DEFAULT_MAX_RETRIES
from workflow.job_queue import JobQueue, Job
from workflow.approval_gate import ApprovalGate, APPROVE_EMOJI, REJECT_EMOJI
from orchestrator import Orchestrator


# --- Fixtures ---

def make_dev_result(passed=True, error=None):
    return DevResult(
        verification_passed=passed,
        worktree_path="/tmp/wt",
        branch="nanoclaw/TASK-001-test",
        details="done",
        files_changed=["main.py"],
        error=error,
    )


def make_task(**overrides):
    task = {
        "id": "TASK-001",
        "title": "Test feature",
        "description": "A test task",
        "status": "open",
        "priority": "medium",
        "dependencies": [],
        "retry_count": 0,
        "max_retries": 2,
        "acceptance_criteria": ["Works correctly"],
        "discord_thread_id": "12345",
    }
    task.update(overrides)
    return task


@pytest.fixture
def mock_pm():
    pm = MagicMock()
    pm.handle = AsyncMock(return_value=json.dumps({
        "tasks": [{
            "title": "Test task",
            "description": "Do something",
            "priority": "high",
            "dependencies": [],
            "acceptance_criteria": ["Works"],
        }]
    }))
    return pm


@pytest.fixture
def mock_dev():
    dev = MagicMock()
    dev.implement = AsyncMock(return_value=make_dev_result())
    dev.commit_and_push = AsyncMock(return_value="https://github.com/pr/1")
    return dev


@pytest.fixture
def mock_qa():
    qa = MagicMock()
    qa.handle = AsyncMock(return_value={
        "passed": True,
        "criteria": [{"criterion": "Works", "passed": True, "notes": "ok"}],
        "feedback": "",
    })
    return qa


@pytest.fixture
def mock_task_store():
    store = MagicMock()
    store.create = AsyncMock()
    store.get = AsyncMock(return_value=make_task())
    store.update = AsyncMock()
    store.list_tasks = AsyncMock(return_value=[make_task()])
    store.increment_retry = AsyncMock()
    return store


@pytest.fixture
def mock_gate():
    gate = MagicMock()
    gate.request = AsyncMock(return_value=True)
    return gate


@pytest.fixture
def engine(mock_pm, mock_dev, mock_qa, mock_task_store, mock_gate):
    return WorkflowEngine(
        pm=mock_pm, dev=mock_dev, qa=mock_qa,
        task_store=mock_task_store,
        approval_gate=mock_gate,
    )


# --- WorkflowEngine Tests ---

@pytest.mark.asyncio
async def test_run_feature_success(engine, mock_pm, mock_dev, mock_qa, mock_gate):
    result = await engine.run_feature("Add health endpoint")
    assert result["session_id"]
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["success"] is True
    assert result["tasks"][0]["pr_url"] == "https://github.com/pr/1"
    mock_pm.handle.assert_called_once()
    mock_dev.implement.assert_called_once()
    mock_qa.handle.assert_called_once()
    mock_gate.request.assert_called_once()
    mock_dev.commit_and_push.assert_called_once()


@pytest.mark.asyncio
async def test_run_feature_qa_fail_then_retry_pass(
    engine, mock_dev, mock_qa, mock_task_store,
):
    # First QA fails, second passes
    mock_qa.handle = AsyncMock(side_effect=[
        {"passed": False, "criteria": [], "feedback": "Fix it"},
        {"passed": True, "criteria": [], "feedback": ""},
    ])
    result = await engine.run_feature("Add feature")
    assert result["tasks"][0]["success"] is True
    assert mock_dev.implement.call_count == 2
    mock_task_store.increment_retry.assert_called_once()


@pytest.mark.asyncio
async def test_run_feature_max_retries_exceeded(
    engine, mock_dev, mock_qa, mock_task_store,
):
    mock_qa.handle = AsyncMock(return_value={
        "passed": False, "criteria": [], "feedback": "Still broken",
    })
    result = await engine.run_feature("Add feature")
    assert result["tasks"][0]["success"] is False
    assert result["tasks"][0]["reason"] == "max retries exceeded"
    # 2 retries + 1 initial = 3 attempts
    assert mock_dev.implement.call_count == 3


@pytest.mark.asyncio
async def test_run_feature_verification_fails(
    engine, mock_dev, mock_task_store,
):
    mock_dev.implement = AsyncMock(
        return_value=make_dev_result(passed=False, error="Syntax error"),
    )
    result = await engine.run_feature("Add feature")
    assert result["tasks"][0]["success"] is False
    assert "verification failed" in result["tasks"][0]["reason"]


@pytest.mark.asyncio
async def test_run_feature_rejected_by_user(engine, mock_gate):
    mock_gate.request = AsyncMock(return_value=False)
    result = await engine.run_feature("Add feature")
    assert result["tasks"][0]["success"] is False
    assert result["tasks"][0]["reason"] == "rejected by user"


@pytest.mark.asyncio
async def test_run_single_task_not_found(engine, mock_task_store):
    mock_task_store.get = AsyncMock(return_value=None)
    result = await engine.run_single_task("TASK-999")
    assert result["success"] is False
    assert "not found" in result["reason"]


@pytest.mark.asyncio
async def test_run_single_task_success(engine, mock_task_store):
    mock_task_store.get = AsyncMock(return_value=make_task())
    result = await engine.run_single_task("TASK-001")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_progress_callback_called(mock_pm, mock_dev, mock_qa,
                                        mock_task_store, mock_gate):
    progress = AsyncMock()
    engine = WorkflowEngine(
        pm=mock_pm, dev=mock_dev, qa=mock_qa,
        task_store=mock_task_store,
        approval_gate=mock_gate,
        progress_callback=progress,
    )
    await engine.run_feature("Add feature")
    assert progress.call_count >= 3  # PM spec, Dev working, QA validating


def test_parse_tasks_valid():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine._max_retries = 2
    spec = json.dumps({"tasks": [{"title": "T1", "description": "D1"}]})
    tasks = engine._parse_tasks(spec)
    assert len(tasks) == 1
    assert tasks[0]["max_retries"] == 2


def test_parse_tasks_bad_json():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine._max_retries = 2
    with pytest.raises(ValueError, match="non-JSON"):
        engine._parse_tasks("not json at all")


def test_parse_tasks_empty():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine._max_retries = 2
    with pytest.raises(ValueError, match="no tasks"):
        engine._parse_tasks('{"tasks": []}')


def test_order_by_dependencies():
    tasks = [
        {"id": "B", "status": "open", "dependencies": ["A"]},
        {"id": "A", "status": "open", "dependencies": []},
        {"id": "C", "status": "open", "dependencies": ["B"]},
    ]
    ordered = WorkflowEngine._order_by_dependencies(tasks)
    ids = [t["id"] for t in ordered]
    assert ids == ["A", "B", "C"]


def test_order_by_dependencies_with_done():
    tasks = [
        {"id": "A", "status": "done", "dependencies": []},
        {"id": "B", "status": "open", "dependencies": ["A"]},
    ]
    ordered = WorkflowEngine._order_by_dependencies(tasks)
    # Only open tasks in output, but B's dep on A (done) is satisfied
    assert len(ordered) == 1
    assert ordered[0]["id"] == "B"


def test_order_by_dependencies_circular():
    tasks = [
        {"id": "A", "status": "open", "dependencies": ["B"]},
        {"id": "B", "status": "open", "dependencies": ["A"]},
    ]
    ordered = WorkflowEngine._order_by_dependencies(tasks)
    # Both have unresolvable deps — appended at end
    assert len(ordered) == 2


# --- JobQueue Tests ---

@pytest.mark.asyncio
async def test_job_queue_enqueue_and_execute():
    queue = JobQueue(max_concurrent=2)
    executed = []

    async def job_fn():
        executed.append("done")

    job = Job(id="j1", fn=job_fn)
    await queue.enqueue(job)

    # Run the worker loop in background, let it process one job
    worker = asyncio.create_task(queue.run())
    await asyncio.sleep(0.1)
    await queue.stop()
    await asyncio.sleep(0.1)
    worker.cancel()

    assert executed == ["done"]


@pytest.mark.asyncio
async def test_job_queue_stop_and_resume():
    queue = JobQueue(max_concurrent=1)
    assert not queue.is_stopped
    await queue.stop()
    assert queue.is_stopped
    await queue.resume()
    assert not queue.is_stopped


@pytest.mark.asyncio
async def test_job_queue_error_handling():
    queue = JobQueue(max_concurrent=1)
    errors = []

    async def bad_fn():
        raise RuntimeError("boom")

    async def on_error(e):
        errors.append(str(e))

    job = Job(id="j2", fn=bad_fn, on_error=on_error)
    await queue.enqueue(job)

    worker = asyncio.create_task(queue.run())
    await asyncio.sleep(0.1)
    await queue.stop()
    await asyncio.sleep(0.1)
    worker.cancel()

    assert errors == ["boom"]


@pytest.mark.asyncio
async def test_job_queue_counts():
    queue = JobQueue(max_concurrent=1)
    assert queue.active_count == 0
    assert queue.queued_count == 0

    async def slow_fn():
        await asyncio.sleep(10)

    await queue.enqueue(Job(id="j3", fn=slow_fn))
    assert queue.queued_count == 1


# --- ApprovalGate Tests ---

@pytest.mark.asyncio
async def test_approval_gate_no_thread_id():
    bot = MagicMock()
    gate = ApprovalGate(bot, timeout_minutes=1)
    task = make_task(discord_thread_id=None)
    result = await gate.request(task, make_dev_result())
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_thread_not_found():
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    gate = ApprovalGate(bot, timeout_minutes=1)
    task = make_task(discord_thread_id="99999")
    result = await gate.request(task, make_dev_result())
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_resolve_approved():
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    gate = ApprovalGate(bot, timeout_minutes=1)
    task = make_task()

    # Start request in background, then resolve it
    async def approve_after_delay():
        await asyncio.sleep(0.05)
        gate.resolve("TASK-001", True)

    asyncio.create_task(approve_after_delay())
    result = await gate.request(task, make_dev_result())
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_resolve_rejected():
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    gate = ApprovalGate(bot, timeout_minutes=1)
    task = make_task()

    async def reject_after_delay():
        await asyncio.sleep(0.05)
        gate.resolve("TASK-001", False)

    asyncio.create_task(reject_after_delay())
    result = await gate.request(task, make_dev_result())
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_pending_ids():
    bot = MagicMock()
    gate = ApprovalGate(bot)
    assert gate.get_pending_task_ids() == []


@pytest.mark.asyncio
async def test_approval_gate_timeout():
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    # Very short timeout for test
    gate = ApprovalGate(bot, timeout_minutes=0)
    gate.timeout = 0.05  # 50ms
    task = make_task()

    result = await gate.request(task, make_dev_result())
    assert result is False


# --- Orchestrator Tests ---

@pytest.fixture
def orchestrator():
    engine = MagicMock()
    engine.run_feature = AsyncMock(return_value={
        "session_id": "abc123", "tasks": [],
    })
    engine.run_single_task = AsyncMock(return_value={
        "task_id": "TASK-001", "success": True, "pr_url": "https://github.com/pr/1",
    })
    engine._noop_progress = AsyncMock()

    task_store = MagicMock()
    task_store.get = AsyncMock(return_value=make_task())
    task_store.update = AsyncMock()
    task_store.list_tasks = AsyncMock(return_value=[
        make_task(status="open"),
        make_task(id="TASK-002", status="done"),
    ])

    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock()
    job_queue.stop = AsyncMock()
    job_queue.resume = AsyncMock()
    job_queue.active_count = 1
    job_queue.queued_count = 0
    job_queue.is_stopped = False

    cost_tracker = MagicMock()
    cost_tracker.daily_total = AsyncMock(return_value=1.23)

    return Orchestrator(
        engine=engine,
        task_store=task_store,
        job_queue=job_queue,
        cost_tracker=cost_tracker,
    )


@pytest.mark.asyncio
async def test_orchestrator_pm_define(orchestrator):
    result = await orchestrator.handle("PM define Add health endpoint", "user1")
    assert "Queued" in result
    orchestrator.job_queue.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_dev_implement(orchestrator):
    result = await orchestrator.handle("Dev implement TASK-001", "user1")
    assert "Queued" in result
    orchestrator.job_queue.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_dev_implement_not_found(orchestrator):
    orchestrator.task_store.get = AsyncMock(return_value=None)
    result = await orchestrator.handle("Dev implement TASK-999", "user1")
    assert "not found" in result


@pytest.mark.asyncio
async def test_orchestrator_stop(orchestrator):
    result = await orchestrator.handle("STOP", "user1")
    assert "stopped" in result.lower()
    orchestrator.job_queue.stop.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_resume(orchestrator):
    result = await orchestrator.handle("RESUME", "user1")
    assert "resumed" in result.lower()
    orchestrator.job_queue.resume.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_status(orchestrator):
    result = await orchestrator.handle("status", "user1")
    assert "NanoClaw Status" in result
    assert "Active jobs: 1" in result
    assert "$1.23" in result


@pytest.mark.asyncio
async def test_orchestrator_cost(orchestrator):
    result = await orchestrator.handle("cost", "user1")
    assert "$1.23" in result


@pytest.mark.asyncio
async def test_orchestrator_cost_zero(orchestrator):
    orchestrator.cost_tracker.daily_total = AsyncMock(return_value=0.0)
    result = await orchestrator.handle("cost", "user1")
    assert "No LLM costs" in result


@pytest.mark.asyncio
async def test_orchestrator_feature_shorthand(orchestrator):
    result = await orchestrator.handle("feature Add logging", "user1")
    assert "Queued" in result


@pytest.mark.asyncio
async def test_orchestrator_unknown_command(orchestrator):
    result = await orchestrator.handle("unknown gibberish", "user1")
    assert "Commands:" in result


@pytest.mark.asyncio
async def test_orchestrator_empty_command(orchestrator):
    result = await orchestrator.handle("", "user1")
    assert "Commands:" in result


# Helper — shared with new approval gate tests
def make_pr_info(number=42):
    return PRInfo(url=f"https://github.com/owner/repo/pull/{number}", number=number)


# --- ApprovalGate dual-signal tests ---

@pytest.mark.asyncio
async def test_approval_gate_github_merge_resolves_gate():
    """Gate resolves True when GitHub PR is merged before Discord reaction."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    # First call returns OPEN, second returns MERGED
    git.get_pr_state = AsyncMock(side_effect=["OPEN", "MERGED"])

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=0.05)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_github_close_resolves_false():
    """Gate resolves False when GitHub PR is closed."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="CLOSED")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=0.05)
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_discord_wins_over_github():
    """Discord reaction resolves gate before GitHub polling does."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="OPEN")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    async def approve_via_discord():
        await asyncio.sleep(0.05)
        gate.resolve("TASK-001", True)

    asyncio.create_task(approve_via_discord())
    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(),
                                poll_interval_seconds=10)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_resolve_by_pr():
    """resolve_by_pr finds and resolves the gate for a given PR number."""
    bot = MagicMock()
    channel = AsyncMock()
    msg = AsyncMock()
    channel.send = AsyncMock(return_value=msg)
    bot.get_channel = MagicMock(return_value=channel)

    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="OPEN")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    gate.timeout = 5.0
    task = make_task()

    async def override_after_delay():
        await asyncio.sleep(0.05)
        resolved = gate.resolve_by_pr(42, True)
        assert resolved is True

    asyncio.create_task(override_after_delay())
    result = await gate.request(task, make_dev_result(),
                                pr_info=make_pr_info(42),
                                poll_interval_seconds=10)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_resolve_by_pr_not_found():
    """resolve_by_pr returns False when no gate exists for the PR number."""
    bot = MagicMock()
    gate = ApprovalGate(bot, timeout_minutes=1)
    result = gate.resolve_by_pr(999, True)
    assert result is False


@pytest.mark.asyncio
async def test_approval_gate_wait_for_github_merge_merged():
    """wait_for_github_merge returns True when state becomes MERGED."""
    bot = MagicMock()
    git = MagicMock()
    git.get_pr_state = AsyncMock(side_effect=["OPEN", "OPEN", "MERGED"])

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    result = await gate.wait_for_github_merge(42, poll_interval_seconds=0.01)
    assert result is True


@pytest.mark.asyncio
async def test_approval_gate_wait_for_github_merge_closed():
    """wait_for_github_merge returns False when state becomes CLOSED."""
    bot = MagicMock()
    git = MagicMock()
    git.get_pr_state = AsyncMock(return_value="CLOSED")

    gate = ApprovalGate(bot, git=git, timeout_minutes=1)
    result = await gate.wait_for_github_merge(42, poll_interval_seconds=0.01)
    assert result is False
