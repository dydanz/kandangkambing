"""ClaudeCodeTool + VerificationLayer — execute Claude Code CLI with output validation."""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("nanoclaw.claude_code")


class VerificationLayer:
    """Run post-Claude-Code checks on the worktree output."""

    async def verify(self, worktree_path: str,
                     task: dict) -> tuple[bool, str]:
        """
        Run checks against the worktree. Returns (passed, details).
        Checks:
        1. Expected files exist (from acceptance criteria hints)
        2. Syntax is clean (python -m py_compile / go vet)
        3. Tests pass (pytest / go test)
        """
        issues = []
        wt = Path(worktree_path)

        if not wt.exists():
            return False, f"Worktree path does not exist: {worktree_path}"

        # Check that some files were actually created or modified
        files = list(wt.rglob("*"))
        source_files = [
            f for f in files
            if f.is_file() and f.suffix in (".py", ".go", ".ts", ".js")
            and "__pycache__" not in str(f)
        ]

        if not source_files:
            issues.append("No source files found in worktree")

        # Python syntax check
        py_files = [f for f in source_files if f.suffix == ".py"]
        for pyf in py_files:
            result = await self._run_cmd(
                ["python", "-m", "py_compile", str(pyf)],
                cwd=worktree_path,
            )
            if not result[0]:
                issues.append(f"Syntax error in {pyf.name}: {result[1]}")

        # Run pytest if tests/ directory exists
        tests_dir = wt / "tests"
        if tests_dir.exists() and list(tests_dir.glob("test_*.py")):
            result = await self._run_cmd(
                ["python", "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
                cwd=worktree_path,
            )
            if not result[0]:
                issues.append(f"Tests failed: {result[1]}")

        if issues:
            return False, "; ".join(issues)
        return True, "All checks passed"

    @staticmethod
    async def _run_cmd(cmd: list[str], cwd: str,
                       timeout: int = 60) -> tuple[bool, str]:
        """Run a command async. Returns (success, output_or_error)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
            if proc.returncode == 0:
                return True, stdout.decode().strip()
            return False, stderr.decode().strip() or stdout.decode().strip()
        except asyncio.TimeoutError:
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            return False, str(e)


class ClaudeCodeTool(Tool):
    name = "claude_code"
    description = "Execute Claude Code CLI in a git worktree"

    def __init__(self, verifier: VerificationLayer):
        self.verifier = verifier

    async def run(self, instruction: str,
                  worktree_path: str = None,
                  task: dict = None,
                  timeout: int = 300,
                  **kwargs) -> ToolResult:
        """
        Run Claude Code CLI, then verify output.
        Returns ToolResult with success=False if verification fails.
        """
        if not worktree_path:
            return ToolResult(
                success=False, output="",
                error="worktree_path is required",
            )

        try:
            # Run Claude Code CLI as subprocess
            cmd = [
                "claude", "-p", instruction,
                "--output-format", "json",
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )

            stdout_text = stdout.decode().strip()
            stderr_text = stderr.decode().strip()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    output=stdout_text,
                    error=f"Claude Code exited with code {proc.returncode}: {stderr_text}",
                )

            # Parse Claude Code JSON output
            claude_output = stdout_text
            try:
                parsed = json.loads(stdout_text)
                claude_output = parsed.get("result", stdout_text)
            except (json.JSONDecodeError, TypeError):
                claude_output = stdout_text

            # Run verification
            if task:
                passed, details = await self.verifier.verify(
                    worktree_path, task,
                )
                if not passed:
                    return ToolResult(
                        success=False,
                        output=claude_output,
                        error=f"Verification failed: {details}",
                        metadata={"verification_details": details},
                    )

            return ToolResult(
                success=True,
                output=claude_output,
                metadata={"verification": "passed"},
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False, output="",
                error=f"Claude Code timed out after {timeout}s",
            )
        except Exception as e:
            logger.error("ClaudeCodeTool error: %s", e)
            return ToolResult(
                success=False, output="",
                error=str(e),
            )
