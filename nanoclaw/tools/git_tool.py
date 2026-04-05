"""GitTool — worktree lifecycle, branch, commit, push, PR creation."""
import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

import git

from tools.base import Tool, ToolResult

logger = logging.getLogger("nanoclaw.git_tool")


class GitTool(Tool):
    name = "git"
    description = "Git operations — worktrees, branches, commits, PRs"

    def __init__(self, repo_path: str, worktree_base: str,
                 github_repo: str = None):
        self.repo = git.Repo(repo_path)
        self.worktree_base = Path(worktree_base)
        self.github_repo = github_repo
        self.worktree_base.mkdir(parents=True, exist_ok=True)

    def create_worktree(self, task_id: str, title: str = "") -> str:
        """Create (or reuse) a git worktree for task. Returns worktree path."""
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
        branch = f"nanoclaw/{task_id}-{slug}" if slug else f"nanoclaw/{task_id}"
        worktree_path = str(self.worktree_base / task_id)

        # Reuse if there's already a valid worktree for this task
        if Path(worktree_path).exists():
            try:
                wt_repo = git.Repo(worktree_path)
                existing_branch = wt_repo.active_branch.name
                if existing_branch.startswith(f"nanoclaw/{task_id}"):
                    logger.info(
                        "Reusing existing worktree %s on branch %s",
                        worktree_path, existing_branch,
                    )
                    return worktree_path
            except Exception:
                pass
            # Stale or broken — remove and recreate
            logger.info("Removing stale worktree %s", worktree_path)
            self.remove_worktree(worktree_path)

        main_ref = self.repo.heads["main"]
        # If the branch already exists (e.g. from a prior partial run), attach to it
        branch_exists = branch in [h.name for h in self.repo.heads]
        if branch_exists:
            self.repo.git.worktree("add", worktree_path, branch)
        else:
            self.repo.git.worktree("add", "-b", branch, worktree_path, main_ref.name)
        logger.info("Created worktree %s on branch %s", worktree_path, branch)
        return worktree_path

    def remove_worktree(self, worktree_path: str) -> None:
        """Remove worktree after task completes or fails."""
        try:
            wt_path = Path(worktree_path)

            # Get branch name before removing worktree
            branch = None
            try:
                wt_repo = git.Repo(worktree_path)
                branch = wt_repo.active_branch.name
            except Exception:
                pass

            # Remove the worktree
            self.repo.git.worktree("remove", worktree_path, "--force")

            # Clean up the branch if it exists
            if branch and branch.startswith("nanoclaw/"):
                try:
                    self.repo.git.branch("-D", branch)
                except git.GitCommandError:
                    pass

            logger.info("Removed worktree %s", worktree_path)
        except Exception as e:
            logger.warning("Failed to remove worktree %s: %s", worktree_path, e)
            # Force cleanup if git worktree remove fails
            if Path(worktree_path).exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

    def commit(self, worktree_path: str, message: str) -> str:
        """Stage all + commit in worktree. Returns short SHA."""
        wt_repo = git.Repo(worktree_path)
        wt_repo.git.add("-A")
        wt_repo.index.commit(message)
        sha = wt_repo.head.commit.hexsha[:8]
        logger.info("Committed %s in %s", sha, worktree_path)
        return sha

    def push(self, worktree_path: str) -> str:
        """Push current branch to remote. Returns branch name.
        Never pushes to main — raises if attempted."""
        wt_repo = git.Repo(worktree_path)
        branch = wt_repo.active_branch.name
        if branch in ("main", "master"):
            raise ValueError("Refusing to push directly to main/master")

        wt_repo.git.push("origin", branch, "--set-upstream")
        logger.info("Pushed branch %s", branch)
        return branch

    async def create_pr(self, title: str, body: str,
                        branch: str, base: str = "main") -> str:
        """Create GitHub PR via gh CLI. Returns PR URL."""
        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch,
            "--base", base,
        ]
        if self.github_repo:
            cmd.extend(["--repo", self.github_repo])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode().strip()
            raise RuntimeError(f"gh pr create failed: {error}")

        pr_url = stdout.decode().strip()
        logger.info("Created PR: %s", pr_url)
        return pr_url

    def get_branch(self, worktree_path: str) -> str:
        """Get the active branch name for a worktree."""
        wt_repo = git.Repo(worktree_path)
        return wt_repo.active_branch.name

    def get_changed_files(self, worktree_path: str) -> list[str]:
        """Get list of changed files in worktree (staged + unstaged + untracked)."""
        wt_repo = git.Repo(worktree_path)
        changed = set()
        # Modified/staged
        for diff in wt_repo.index.diff(None):
            changed.add(diff.a_path)
        for diff in wt_repo.index.diff("HEAD"):
            changed.add(diff.a_path)
        # Untracked
        changed.update(wt_repo.untracked_files)
        return sorted(changed)

    async def run(self, input: str, **kwargs) -> ToolResult:
        """Generic Tool interface — not used directly; use specific methods."""
        return ToolResult(
            success=False, output="",
            error="Use specific GitTool methods instead of run()",
        )
