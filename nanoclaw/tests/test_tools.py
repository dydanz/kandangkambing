"""Tests for Tools — VerificationLayer, GitTool, ToolRegistry, ClaudeCodeTool (PR4)."""
import asyncio
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import git
import pytest

from tools.base import Tool, ToolResult
from tools.tool_registry import ToolRegistry
from tools.claude_code import VerificationLayer, ClaudeCodeTool
from tools.git_tool import GitTool


# --- ToolRegistry ---

class DummyTool(Tool):
    name = "dummy"
    description = "A dummy tool for testing"

    async def run(self, input: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=f"dummy: {input}")


@pytest.mark.asyncio
async def test_registry_register_and_invoke():
    reg = ToolRegistry()
    reg.register(DummyTool())
    result = await reg.invoke("dummy", "hello")
    assert result.success
    assert result.output == "dummy: hello"


@pytest.mark.asyncio
async def test_registry_invoke_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError, match="not registered"):
        await reg.invoke("unknown", "hello")


def test_registry_get():
    reg = ToolRegistry()
    reg.register(DummyTool())
    assert reg.get("dummy") is not None
    assert reg.get("nonexistent") is None


def test_registry_list_tools():
    reg = ToolRegistry()
    reg.register(DummyTool())
    tools = reg.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "dummy"
    assert tools[0]["description"] == "A dummy tool for testing"


# --- VerificationLayer ---

@pytest.fixture
def worktree_with_python(tmp_path):
    """Create a fake worktree with a valid Python file."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / "main.py").write_text("x = 1\n")
    return str(wt)


@pytest.fixture
def worktree_with_syntax_error(tmp_path):
    """Create a fake worktree with a Python syntax error."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / "bad.py").write_text("def foo(\n")
    return str(wt)


@pytest.fixture
def empty_worktree(tmp_path):
    """Create a fake worktree with no source files."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / "README.md").write_text("# nothing here")
    return str(wt)


@pytest.mark.asyncio
async def test_verification_passes_valid_python(worktree_with_python):
    v = VerificationLayer()
    task = {"id": "TASK-001", "acceptance_criteria": []}
    passed, details = await v.verify(worktree_with_python, task)
    assert passed is True
    assert "passed" in details.lower()


@pytest.mark.asyncio
async def test_verification_fails_syntax_error(worktree_with_syntax_error):
    v = VerificationLayer()
    task = {"id": "TASK-001", "acceptance_criteria": []}
    passed, details = await v.verify(worktree_with_syntax_error, task)
    assert passed is False
    assert "syntax" in details.lower() or "error" in details.lower()


@pytest.mark.asyncio
async def test_verification_fails_no_source_files(empty_worktree):
    v = VerificationLayer()
    task = {"id": "TASK-001", "acceptance_criteria": []}
    passed, details = await v.verify(empty_worktree, task)
    assert passed is False
    assert "no source files" in details.lower()


@pytest.mark.asyncio
async def test_verification_fails_nonexistent_path():
    v = VerificationLayer()
    task = {"id": "TASK-001", "acceptance_criteria": []}
    passed, details = await v.verify("/nonexistent/path", task)
    assert passed is False
    assert "does not exist" in details.lower()


# --- GitTool ---

@pytest.fixture
def git_env(tmp_path):
    """Create a real git repo + worktree base for testing."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = git.Repo.init(repo_path)

    # Create initial commit on main
    readme = repo_path / "README.md"
    readme.write_text("# Test repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")

    # Ensure we're on main branch
    if repo.active_branch.name != "main":
        repo.git.branch("-m", repo.active_branch.name, "main")

    worktree_base = tmp_path / "worktrees"
    worktree_base.mkdir()

    return {
        "repo_path": str(repo_path),
        "worktree_base": str(worktree_base),
        "repo": repo,
    }


@pytest.fixture
def git_tool(git_env):
    return GitTool(
        repo_path=git_env["repo_path"],
        worktree_base=git_env["worktree_base"],
        github_repo="test/test-repo",
    )


def test_git_create_worktree(git_tool, git_env):
    wt_path = git_tool.create_worktree("TASK-001", "add health endpoint")
    assert Path(wt_path).exists()
    # Should have a git repo
    wt_repo = git.Repo(wt_path)
    assert wt_repo.active_branch.name.startswith("nanoclaw/TASK-001")
    # Clean up
    git_tool.remove_worktree(wt_path)


def test_git_create_worktree_reuse(git_tool):
    """Second call for the same task_id reuses the existing worktree."""
    wt_path1 = git_tool.create_worktree("TASK-001R", "reuse test")
    # Write a file so we can detect if it survives the second call
    sentinel = Path(wt_path1) / "sentinel.txt"
    sentinel.write_text("keep me")
    wt_path2 = git_tool.create_worktree("TASK-001R", "reuse test")
    assert wt_path1 == wt_path2
    assert sentinel.exists(), "Existing worktree was destroyed instead of reused"
    git_tool.remove_worktree(wt_path1)


def test_git_create_worktree_slug(git_tool):
    wt_path = git_tool.create_worktree("TASK-002", "Fix Bug #123!")
    branch = git_tool.get_branch(wt_path)
    assert "fix-bug-123" in branch
    git_tool.remove_worktree(wt_path)


def test_git_remove_worktree(git_tool):
    wt_path = git_tool.create_worktree("TASK-003")
    assert Path(wt_path).exists()
    git_tool.remove_worktree(wt_path)
    assert not Path(wt_path).exists()


def test_git_remove_worktree_idempotent(git_tool):
    """Removing a non-existent worktree should not raise."""
    git_tool.remove_worktree("/tmp/nonexistent-worktree-path")


def test_git_commit(git_tool):
    wt_path = git_tool.create_worktree("TASK-004")
    # Create a file in worktree
    (Path(wt_path) / "new_file.py").write_text("x = 1\n")
    sha = git_tool.commit(wt_path, "Add new file")
    assert len(sha) == 8
    # Verify commit exists
    wt_repo = git.Repo(wt_path)
    assert wt_repo.head.commit.message == "Add new file"
    git_tool.remove_worktree(wt_path)


def test_git_get_changed_files(git_tool):
    wt_path = git_tool.create_worktree("TASK-005")
    (Path(wt_path) / "a.py").write_text("a = 1\n")
    (Path(wt_path) / "b.py").write_text("b = 2\n")
    changed = git_tool.get_changed_files(wt_path)
    assert "a.py" in changed
    assert "b.py" in changed
    git_tool.remove_worktree(wt_path)


def test_git_push_refuses_main(git_env):
    """Push to main should be refused."""
    # Use a fresh repo where we can be on main directly
    repo_path = git_env["repo_path"]
    tool = GitTool(
        repo_path=repo_path,
        worktree_base=git_env["worktree_base"],
    )
    # The main repo itself is on main
    with pytest.raises(ValueError, match="main"):
        tool.push(repo_path)


# --- ClaudeCodeTool ---

@pytest.mark.asyncio
async def test_claude_code_requires_worktree_path():
    verifier = VerificationLayer()
    tool = ClaudeCodeTool(verifier)
    result = await tool.run("do something")
    assert not result.success
    assert "worktree_path is required" in result.error


@pytest.mark.asyncio
async def test_claude_code_calls_verification(worktree_with_python):
    """ClaudeCodeTool should call verification after running Claude Code."""
    verifier = VerificationLayer()
    verifier.verify = AsyncMock(return_value=(True, "All checks passed"))
    tool = ClaudeCodeTool(verifier)

    # Mock the subprocess to simulate Claude Code success
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"result": "done"}', b"")
        )
        mock_exec.return_value = mock_proc

        task = {"id": "TASK-001", "acceptance_criteria": []}
        result = await tool.run(
            "implement feature",
            worktree_path=worktree_with_python,
            task=task,
        )

    assert result.success
    verifier.verify.assert_called_once()


@pytest.mark.asyncio
async def test_claude_code_verification_failure(worktree_with_python):
    """ClaudeCodeTool returns failure when verification fails."""
    verifier = VerificationLayer()
    verifier.verify = AsyncMock(return_value=(False, "Tests failed"))
    tool = ClaudeCodeTool(verifier)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
        mock_exec.return_value = mock_proc

        task = {"id": "TASK-001", "acceptance_criteria": []}
        result = await tool.run(
            "implement feature",
            worktree_path=worktree_with_python,
            task=task,
        )

    assert not result.success
    assert "Verification failed" in result.error


@pytest.mark.asyncio
async def test_claude_code_subprocess_failure(worktree_with_python):
    """ClaudeCodeTool handles non-zero exit code from Claude Code."""
    verifier = VerificationLayer()
    tool = ClaudeCodeTool(verifier)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"error occurred")
        )
        mock_exec.return_value = mock_proc

        result = await tool.run(
            "implement feature",
            worktree_path=worktree_with_python,
            task={"id": "TASK-001"},
        )

    assert not result.success
    assert "exited with code 1" in result.error


# --- GitTool PR methods ---

@pytest.mark.asyncio
async def test_git_tool_get_pr_diff_success():
    """get_pr_diff returns stdout from gh pr diff."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"diff --git a/f.py b/f.py\n+new line", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        result = await git_tool.get_pr_diff(42)

    assert result == "diff --git a/f.py b/f.py\n+new line"
    call_args = mock_exec.call_args[0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "diff" in call_args
    assert "42" in call_args


@pytest.mark.asyncio
async def test_git_tool_get_pr_diff_failure():
    """get_pr_diff raises RuntimeError on non-zero exit."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"not found"))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"

        with pytest.raises(RuntimeError, match="gh pr diff failed"):
            await git_tool.get_pr_diff(99)


@pytest.mark.asyncio
async def test_git_tool_get_pr_state_merged():
    """get_pr_state returns MERGED when gh reports it."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"MERGED\n", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        state = await git_tool.get_pr_state(42)

    assert state == "MERGED"


@pytest.mark.asyncio
async def test_git_tool_get_pr_state_open():
    """get_pr_state returns OPEN for an open PR."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"OPEN\n", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        state = await git_tool.get_pr_state(42)

    assert state == "OPEN"


@pytest.mark.asyncio
async def test_git_tool_post_pr_review_success():
    """post_pr_review calls gh pr review with --comment."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"
        await git_tool.post_pr_review(42, "## Review\nLooks good!")

    call_args = mock_exec.call_args[0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "review" in call_args
    assert "--comment" in call_args


@pytest.mark.asyncio
async def test_git_tool_post_pr_review_failure():
    """post_pr_review raises RuntimeError on non-zero exit."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"auth error"))
        mock_exec.return_value = proc

        git_tool = GitTool.__new__(GitTool)
        git_tool.github_repo = "owner/repo"

        with pytest.raises(RuntimeError, match="gh pr review failed"):
            await git_tool.post_pr_review(42, "body")
