"""WorkflowEngine — PM→Dev→QA orchestration loop with retry and approval."""
import json
import logging
import uuid
from typing import Callable, Awaitable, Optional

from agents.pm import PMAgent
from agents.dev import DevAgent
from agents.qa import QAAgent
from memory.task_store import TaskStore
from workflow.approval_gate import ApprovalGate

logger = logging.getLogger("nanoclaw.workflow.engine")

# Default max_retries used when not in task or settings
DEFAULT_MAX_RETRIES = 2


class WorkflowEngine:
    def __init__(self, pm: PMAgent, dev: DevAgent, qa: QAAgent,
                 task_store: TaskStore, approval_gate: ApprovalGate,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 progress_callback: Optional[Callable] = None):
        self.pm = pm
        self.dev = dev
        self.qa = qa
        self.task_store = task_store
        self.gate = approval_gate
        self._max_retries = max_retries
        self._progress = progress_callback or self._noop_progress

    @staticmethod
    async def _noop_progress(msg: str) -> None:
        pass

    async def run_feature(self, instruction: str,
                          session_id: str = None) -> dict:
        """Full PM→Dev→QA workflow for a feature request."""
        session_id = session_id or str(uuid.uuid4())
        await self._progress("PM Agent creating spec...")

        spec = await self.pm.handle(instruction, session_id=session_id)
        tasks = self._parse_tasks(spec)

        # Persist tasks to store
        for task_data in tasks:
            await self.task_store.create(
                title=task_data.get("title", ""),
                description=task_data.get("description", ""),
                priority=task_data.get("priority", "medium"),
                dependencies=task_data.get("dependencies", []),
                acceptance_criteria=task_data.get("acceptance_criteria", []),
                max_retries=task_data.get("max_retries", self._max_retries),
            )

        # Re-read from store to get generated IDs
        all_tasks = await self.task_store.list_tasks()
        ordered = self._order_by_dependencies(all_tasks)

        results = []
        for task in ordered:
            if task["status"] != "open":
                continue
            result = await self._run_task(task, session_id)
            results.append(result)
            if not result["success"]:
                break

        return {"session_id": session_id, "tasks": results}

    async def run_single_task(self, task_id: str,
                              session_id: str = None) -> dict:
        """Run Dev→QA loop for a specific existing task."""
        session_id = session_id or str(uuid.uuid4())
        task = await self.task_store.get(task_id)
        if not task:
            return {"task_id": task_id, "success": False,
                    "reason": f"Task {task_id} not found"}
        return await self._run_task(task, session_id)

    async def _run_task(self, task: dict, session_id: str) -> dict:
        """Dev → QA → retry loop for one task.

        retry_count is incremented ONCE per failed attempt,
        regardless of whether failure came from verification or QA.
        Only incremented when a subsequent attempt will follow.
        """
        max_retries = task.get("max_retries", self._max_retries)
        for attempt in range(max_retries + 1):
            await self._progress(
                f"Dev working on {task['id']} "
                f"(attempt {attempt + 1}/{max_retries + 1})..."
            )
            dev_result = await self.dev.implement(task, session_id)

            if not dev_result.verification_passed:
                if attempt >= max_retries:
                    await self._progress(
                        f"{task['id']} verification failed after "
                        f"{max_retries} retries. Manual intervention needed."
                    )
                    return {"task_id": task["id"], "success": False,
                            "reason": "verification failed, max retries exceeded",
                            "details": dev_result.error}
                await self.task_store.increment_retry(task["id"])
                continue

            await self._progress(f"QA validating {task['id']}...")
            qa_result = await self.qa.handle(
                task=task, dev_result=dev_result, session_id=session_id
            )

            if qa_result["passed"]:
                await self._progress(
                    f"{task['id']} ready — awaiting your approval"
                )
                approved = await self.gate.request(task, dev_result)
                if approved:
                    pr_url = await self.dev.commit_and_push(task, dev_result)
                    return {"task_id": task["id"], "success": True,
                            "pr_url": pr_url}
                else:
                    await self.task_store.update(task["id"], status="failed")
                    return {"task_id": task["id"], "success": False,
                            "reason": "rejected by user"}

            # QA failed
            if attempt >= max_retries:
                await self._progress(
                    f"{task['id']} failed after {max_retries} retries. "
                    f"Manual intervention needed."
                )
                await self.task_store.update(task["id"], status="failed")
                return {"task_id": task["id"], "success": False,
                        "reason": "max retries exceeded",
                        "qa_result": qa_result}
            await self.task_store.increment_retry(task["id"])

        return {"task_id": task["id"], "success": False, "reason": "unknown"}

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences if present, then return the raw JSON string."""
        text = text.strip()
        # Handle ```json ... ``` or ``` ... ```
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first line (```json or ```) and last line (```)
            inner = lines[1:] if lines[-1].strip() == "```" else lines[1:]
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            text = "\n".join(inner).strip()
        return text

    def _parse_tasks(self, spec: str) -> list[dict]:
        """Parse PM JSON output into task dicts. Raises ValueError on bad JSON."""
        try:
            data = json.loads(self._extract_json(spec))
        except json.JSONDecodeError as e:
            raise ValueError(f"PM returned non-JSON output: {e}") from e
        tasks = data.get("tasks", [])
        if not tasks:
            raise ValueError("PM returned no tasks")
        for task in tasks:
            task.setdefault("max_retries", self._max_retries)
        return tasks

    @staticmethod
    def _order_by_dependencies(tasks: list[dict]) -> list[dict]:
        """Topological sort — tasks with no unmet deps come first."""
        done_ids = {t["id"] for t in tasks if t["status"] == "done"}
        remaining = [t for t in tasks if t["status"] != "done"]

        ordered = []
        seen = set(done_ids)
        changed = True
        while changed and remaining:
            changed = False
            next_remaining = []
            for t in remaining:
                deps = set(t.get("dependencies", []))
                if deps.issubset(seen):
                    ordered.append(t)
                    seen.add(t["id"])
                    changed = True
                else:
                    next_remaining.append(t)
            remaining = next_remaining

        # Append any with unresolvable deps at the end
        ordered.extend(remaining)
        return ordered
