"""Tests for Agents — BaseAgent, PMAgent, DevAgent, QAAgent (PR5)."""
import json
import json as json_module
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.providers.base import LLMResponse
from agents.base import BaseAgent
from agents.pm import PMAgent
from agents.dev import DevAgent, DevResult, PRInfo
from agents.qa import QAAgent
from agents.code_reviewer import CodeReviewerAgent, ReviewResult, Finding


# --- Shared mocks ---

def make_router(response_content="test response"):
    router = MagicMock()
    router.route = AsyncMock(return_value=LLMResponse(
        content=response_content,
        model="test-model",
        provider="test",
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.001,
    ))
    return router


def make_memory():
    memory = MagicMock()
    memory.get_recent = AsyncMock(return_value=[])
    memory.save_message = AsyncMock()
    return memory


def make_context():
    context = MagicMock()
    context.load_all = AsyncMock(return_value="# Project\nTest project")
    return context


# --- BaseAgent ---

@pytest.mark.asyncio
async def test_base_agent_handle():
    router = make_router("Hello from LLM")
    memory = make_memory()
    context = make_context()

    agent = BaseAgent(router, memory, context)
    agent.name = "test"
    agent.task_type = "simple"

    result = await agent.handle("Do something", task_id="TASK-001",
                                 session_id="s1")
    assert result == "Hello from LLM"

    # Verify router was called
    router.route.assert_called_once()
    call_kwargs = router.route.call_args
    assert call_kwargs.kwargs["task_type"] == "simple"
    assert call_kwargs.kwargs["agent"] == "test"

    # Verify saved to memory
    memory.save_message.assert_called_once()
    save_kwargs = memory.save_message.call_args.kwargs
    assert save_kwargs["role"] == "test"
    assert save_kwargs["content"] == "Hello from LLM"
    assert save_kwargs["task_id"] == "TASK-001"


@pytest.mark.asyncio
async def test_base_agent_builds_messages_with_context():
    router = make_router()
    memory = make_memory()
    context = make_context()

    agent = BaseAgent(router, memory, context)
    agent.name = "test"
    agent.task_type = "simple"

    await agent.handle("instruction here")

    messages = router.route.call_args.kwargs["messages"]
    # Should have system + user message
    assert messages[0]["role"] == "system"
    assert "Project Context" in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "instruction here"


@pytest.mark.asyncio
async def test_base_agent_includes_history():
    router = make_router()
    memory = make_memory()
    memory.get_recent = AsyncMock(return_value=[
        {"role": "user", "agent": "user", "content": "prev msg", "timestamp": "t"},
        {"role": "dev", "agent": "dev", "content": "prev reply", "timestamp": "t"},
    ])
    context = make_context()

    agent = BaseAgent(router, memory, context)
    agent.name = "dev"
    agent.task_type = "coding"

    await agent.handle("new instruction")

    messages = router.route.call_args.kwargs["messages"]
    # system + 2 history + 1 current = 4
    assert len(messages) == 4
    assert messages[1]["role"] == "user"  # history from different agent
    assert messages[2]["role"] == "assistant"  # history from same agent


@pytest.mark.asyncio
async def test_base_agent_loads_prompt_from_file(tmp_path):
    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("You are a custom agent.")

    router = make_router()
    memory = make_memory()
    context = MagicMock()
    context.load_all = AsyncMock(return_value="")

    agent = BaseAgent(router, memory, context)
    agent.name = "custom"
    agent.task_type = "simple"
    agent.prompt_file = str(prompt_file)

    await agent.handle("test")

    messages = router.route.call_args.kwargs["messages"]
    assert "custom agent" in messages[0]["content"]


# --- PMAgent ---

@pytest.mark.asyncio
async def test_pm_agent_returns_json():
    pm_response = json.dumps({
        "feature": "Health endpoint",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "Add /health",
                "description": "GET /health returning 200",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Returns 200"]
            }
        ]
    })
    router = make_router(pm_response)
    memory = make_memory()
    context = make_context()

    pm = PMAgent(router, memory, context)
    result = await pm.handle("Add a health check endpoint")

    # Result should be parseable JSON
    parsed = json.loads(result)
    assert parsed["feature"] == "Health endpoint"
    assert len(parsed["tasks"]) == 1


def test_pm_agent_properties():
    pm = PMAgent(make_router(), make_memory(), make_context())
    assert pm.name == "pm"
    assert pm.task_type == "spec"
    assert pm.prompt_file == "config/prompts/pm_prompt.md"


# --- DevAgent ---

@pytest.fixture
def dev_agent():
    router = make_router()
    memory = make_memory()
    context = make_context()
    claude_code = MagicMock()
    claude_code.run = AsyncMock()
    git = MagicMock()
    task_store = MagicMock()
    task_store.update = AsyncMock()

    agent = DevAgent(router, memory, context, claude_code, git, task_store)
    return agent


@pytest.mark.asyncio
async def test_dev_implement_success(dev_agent):
    dev_agent.git.create_worktree.return_value = "/tmp/wt"
    dev_agent.git.get_branch.return_value = "nanoclaw/TASK-001-test"
    dev_agent.git.get_changed_files.return_value = ["main.py"]
    dev_agent.claude_code.run = AsyncMock(return_value=MagicMock(
        success=True, output="Implemented feature", error=None,
    ))

    task = {
        "id": "TASK-001", "title": "Add feature",
        "description": "desc", "acceptance_criteria": ["Works"],
    }
    result = await dev_agent.implement(task, session_id="s1")

    assert isinstance(result, DevResult)
    assert result.verification_passed is True
    assert result.worktree_path == "/tmp/wt"
    assert result.branch == "nanoclaw/TASK-001-test"
    assert result.files_changed == ["main.py"]
    assert result.error is None


@pytest.mark.asyncio
async def test_dev_implement_failure(dev_agent):
    dev_agent.git.create_worktree.return_value = "/tmp/wt"
    dev_agent.git.get_branch.return_value = "nanoclaw/TASK-001-test"
    dev_agent.git.get_changed_files.return_value = []
    dev_agent.claude_code.run = AsyncMock(return_value=MagicMock(
        success=False, output="", error="Syntax error in main.py",
    ))

    task = {"id": "TASK-001", "title": "Add feature",
            "description": "desc", "acceptance_criteria": []}
    result = await dev_agent.implement(task)

    assert result.verification_passed is False
    assert result.error == "Syntax error in main.py"


@pytest.mark.asyncio
async def test_dev_commit_and_push(dev_agent):
    dev_agent.git.commit.return_value = "abc12345"
    dev_agent.git.create_pr = AsyncMock(return_value="https://github.com/pr/1")

    task = {"id": "TASK-001", "title": "Add feature",
            "description": "desc", "acceptance_criteria": ["Works"]}
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="nanoclaw/TASK-001", details="done",
        files_changed=["main.py"],
    )

    pr_info = await dev_agent.commit_and_push(task, dev_result)

    assert isinstance(pr_info, PRInfo)
    assert pr_info.url == "https://github.com/pr/1"
    assert pr_info.number == 1
    dev_agent.git.commit.assert_called_once()
    dev_agent.git.push.assert_called_once_with("/tmp/wt")
    dev_agent.git.create_pr.assert_called_once()
    dev_agent.git.remove_worktree.assert_called_once_with("/tmp/wt")


@pytest.mark.asyncio
async def test_dev_commit_and_push_returns_prinfo():
    """commit_and_push should return PRInfo(url, number)."""
    router = make_router()
    memory = make_memory()
    context = make_context()

    git = MagicMock()
    git.commit = MagicMock(return_value="abc123")
    git.push = MagicMock(return_value="nanoclaw/TASK-001-test")
    git.create_pr = AsyncMock(return_value="https://github.com/owner/repo/pull/42")
    git.remove_worktree = MagicMock()

    task_store = MagicMock()
    task_store.update = AsyncMock()

    agent = DevAgent(router, memory, context, MagicMock(), git, task_store)
    task = {
        "id": "TASK-001", "title": "test", "description": "desc",
        "acceptance_criteria": [],
    }
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="nanoclaw/TASK-001-test", details="done", files_changed=["a.py"],
    )

    pr_info = await agent.commit_and_push(task, dev_result)

    assert isinstance(pr_info, PRInfo)
    assert pr_info.url == "https://github.com/owner/repo/pull/42"
    assert pr_info.number == 42


def test_pr_info_number_extracted_from_url():
    """PRInfo.number is the integer at the end of the GitHub URL."""
    info = PRInfo(url="https://github.com/owner/repo/pull/123", number=123)
    assert info.number == 123


def test_dev_build_instruction(dev_agent):
    task = {
        "id": "TASK-001", "title": "Add endpoint",
        "description": "Create GET /health",
        "acceptance_criteria": ["Returns 200", "Has tests"],
    }
    instruction = dev_agent._build_instruction(task)
    assert "Add endpoint" in instruction
    assert "Create GET /health" in instruction
    assert "Returns 200" in instruction
    assert "Has tests" in instruction


# --- QAAgent ---

@pytest.mark.asyncio
async def test_qa_handle_pass():
    qa_response = json.dumps({
        "passed": True,
        "criteria": [
            {"criterion": "Returns 200", "passed": True, "notes": "Verified"}
        ],
        "feedback": "All good",
    })
    router = make_router(qa_response)
    memory = make_memory()
    context = make_context()

    qa = QAAgent(router, memory, context)
    task = {"id": "TASK-001", "title": "Test",
            "acceptance_criteria": ["Returns 200"]}
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="b", details="done", files_changed=["f.py"],
    )

    result = await qa.handle(task, dev_result, session_id="s1")
    assert result["passed"] is True
    assert len(result["criteria"]) == 1
    assert result["criteria"][0]["passed"] is True


@pytest.mark.asyncio
async def test_qa_handle_fail():
    qa_response = json.dumps({
        "passed": False,
        "criteria": [
            {"criterion": "Returns 200", "passed": False,
             "notes": "Returns 500 instead"}
        ],
        "feedback": "Fix the status code",
    })
    router = make_router(qa_response)
    memory = make_memory()
    context = make_context()

    qa = QAAgent(router, memory, context)
    task = {"id": "TASK-001", "title": "Test",
            "acceptance_criteria": ["Returns 200"]}
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="b", details="done", files_changed=["f.py"],
    )

    result = await qa.handle(task, dev_result)
    assert result["passed"] is False
    assert "Fix the status code" in result["feedback"]


def test_qa_parse_response_json():
    raw = json.dumps({"passed": True, "criteria": [], "feedback": "ok"})
    result = QAAgent._parse_qa_response(raw, {"acceptance_criteria": []})
    assert result["passed"] is True


def test_qa_parse_response_with_surrounding_text():
    raw = 'Here is my review:\n{"passed": false, "criteria": [], "feedback": "fix"}\nEnd.'
    result = QAAgent._parse_qa_response(raw, {"acceptance_criteria": []})
    assert result["passed"] is False


def test_qa_parse_response_fallback_on_bad_json():
    raw = "All criteria met. Everything looks good."
    result = QAAgent._parse_qa_response(
        raw, {"acceptance_criteria": ["Criterion A"]},
    )
    assert result["passed"] is True
    assert len(result["criteria"]) == 1


def test_qa_parse_response_fallback_fail():
    raw = "The implementation has issues. Fix the error handling."
    result = QAAgent._parse_qa_response(
        raw, {"acceptance_criteria": ["Handle errors"]},
    )
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_qa_saves_to_memory():
    router = make_router('{"passed": true, "criteria": [], "feedback": "ok"}')
    memory = make_memory()
    context = make_context()

    qa = QAAgent(router, memory, context)
    task = {"id": "TASK-001", "title": "Test", "acceptance_criteria": []}
    dev_result = DevResult(
        verification_passed=True, worktree_path="/tmp/wt",
        branch="b", details="done", files_changed=[],
    )

    await qa.handle(task, dev_result)
    memory.save_message.assert_called_once()
    save_kwargs = memory.save_message.call_args.kwargs
    assert save_kwargs["role"] == "qa"
    assert save_kwargs["task_id"] == "TASK-001"


# --- CodeReviewerAgent ---

def make_git_mock(diff="diff --git a/f.py\n+line"):
    git = MagicMock()
    git.get_pr_diff = AsyncMock(return_value=diff)
    git.post_pr_review = AsyncMock()
    return git


@pytest.mark.asyncio
async def test_code_reviewer_returns_review_result():
    """review() returns a ReviewResult with structured findings."""
    response_json = json_module.dumps({
        "critical": [{"location": "app.py:10", "issue": "SQL injection", "fix": "Use params"}],
        "important": [],
        "suggestions": [],
        "positives": ["Good error handling"],
        "summary": "One critical issue found.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=42, task_id="TASK-001", session_id="s1")

    assert isinstance(result, ReviewResult)
    assert result.pr_number == 42
    assert result.has_critical is True
    assert len(result.critical) == 1
    assert result.critical[0].location == "app.py:10"
    assert result.critical[0].issue == "SQL injection"
    assert result.positives == ["Good error handling"]


@pytest.mark.asyncio
async def test_code_reviewer_posts_github_comment():
    """review() calls post_pr_review with formatted markdown."""
    response_json = json_module.dumps({
        "critical": [],
        "important": [],
        "suggestions": [],
        "positives": ["Clean code"],
        "summary": "No issues.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=7)

    git.post_pr_review.assert_called_once()
    call_args = git.post_pr_review.call_args
    assert call_args[0][0] == 7  # pr_number
    body = call_args[0][1]
    assert "NanoClaw AI Code Review" in body
    assert result.github_comment_posted is True


@pytest.mark.asyncio
async def test_code_reviewer_fallback_on_bad_json():
    """review() returns empty-severity ReviewResult when LLM returns non-JSON."""
    router = make_router("I cannot review this code.")
    memory = make_memory()
    context = make_context()
    git = make_git_mock()

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=5)

    assert result.pr_number == 5
    assert result.has_critical is False
    assert result.summary == "I cannot review this code."


@pytest.mark.asyncio
async def test_code_reviewer_github_post_failure_doesnt_raise():
    """review() logs warning and continues if post_pr_review fails."""
    response_json = json_module.dumps({
        "critical": [], "important": [], "suggestions": [],
        "positives": [], "summary": "All good.",
    })
    router = make_router(response_json)
    memory = make_memory()
    context = make_context()
    git = make_git_mock()
    git.post_pr_review = AsyncMock(side_effect=RuntimeError("gh auth error"))

    agent = CodeReviewerAgent(router, memory, context, git)
    result = await agent.review(pr_number=3)

    # Should not raise — just mark comment as not posted
    assert result.github_comment_posted is False


def test_review_result_has_critical_false_when_empty():
    result = ReviewResult(
        pr_number=1, critical=[], important=[], suggestions=[],
        positives=[], summary="", github_comment_posted=False,
    )
    assert result.has_critical is False


def test_review_result_has_critical_true_when_findings():
    finding = Finding(location="a.py:1", issue="bug", fix="fix it")
    result = ReviewResult(
        pr_number=1, critical=[finding], important=[], suggestions=[],
        positives=[], summary="", github_comment_posted=False,
    )
    assert result.has_critical is True
