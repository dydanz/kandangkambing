"""Tests for GitTool.write_and_commit()."""
import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal real git repo in a temp directory."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    # Initial commit so HEAD exists
    (repo_dir / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )
    return repo_dir


@pytest.mark.asyncio
async def test_write_and_commit_creates_file(fake_repo, tmp_path):
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/oauth.md",
        content="# OAuth\n\n## Summary\nTest content.",
        message="docs(cto): add oauth research doc",
    )

    written = fake_repo / "docs" / "research" / "oauth.md"
    assert written.exists()
    assert "OAuth" in written.read_text()


@pytest.mark.asyncio
async def test_write_and_commit_makes_a_commit(fake_repo, tmp_path):
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/notes.md",
        content="# Notes",
        message="docs(cto): add notes",
    )

    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(fake_repo), capture_output=True, text=True,
    )
    assert "docs(cto): add notes" in result.stdout


@pytest.mark.asyncio
async def test_write_and_commit_creates_parent_dirs(fake_repo, tmp_path):
    from tools.git_tool import GitTool
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    tool = GitTool(str(fake_repo), str(worktrees))

    await tool.write_and_commit(
        path="docs/research/deep/nested/file.md",
        content="# Deep",
        message="test nested dirs",
    )

    assert (fake_repo / "docs" / "research" / "deep" / "nested" / "file.md").exists()
