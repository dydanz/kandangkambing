"""TaskStore — task CRUD with dependency resolution, backed by JSON file."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class TaskStore:
    def __init__(self, path: str = "memory/tasks.json"):
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._counter = 0
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"tasks": []}, indent=2))

    def _read(self) -> list[dict]:
        data = json.loads(self.path.read_text())
        return data.get("tasks", [])

    def _write(self, tasks: list[dict]) -> None:
        self.path.write_text(json.dumps({"tasks": tasks}, indent=2))

    def _next_id(self, tasks: list[dict]) -> str:
        existing = [t["id"] for t in tasks]
        n = len(tasks) + 1
        while True:
            task_id = f"TASK-{n:03d}"
            if task_id not in existing:
                return task_id
            n += 1

    async def create(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        dependencies: list[str] = None,
        acceptance_criteria: list[str] = None,
        max_retries: int = 2,
    ) -> dict:
        """Create a new task. Returns the created task dict."""
        async with self._lock:
            tasks = self._read()
            now = datetime.now(timezone.utc).isoformat()
            task = {
                "id": self._next_id(tasks),
                "title": title,
                "description": description,
                "status": "open",
                "priority": priority,
                "created_by": "pm",
                "assigned_to": "dev",
                "dependencies": dependencies or [],
                "retry_count": 0,
                "max_retries": max_retries,
                "acceptance_criteria": acceptance_criteria or [],
                "worktree_path": None,
                "branch": None,
                "verification": {
                    "files_created": [],
                    "tests_passed": None,
                    "syntax_clean": None,
                    "last_verified_at": None,
                },
                "pr_url": None,
                "discord_thread_id": None,
                "created_at": now,
                "updated_at": now,
            }
            tasks.append(task)
            self._write(tasks)
            return task

    async def get(self, task_id: str) -> Optional[dict]:
        """Get task by ID. Returns None if not found."""
        async with self._lock:
            for t in self._read():
                if t["id"] == task_id:
                    return t
            return None

    async def update(self, task_id: str, **fields) -> dict:
        """Update task fields. Raises KeyError if task not found."""
        async with self._lock:
            tasks = self._read()
            for t in tasks:
                if t["id"] == task_id:
                    t.update(fields)
                    t["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write(tasks)
                    return t
            raise KeyError(f"Task {task_id} not found")

    async def list_tasks(self, status: str = None) -> list[dict]:
        """List tasks, optionally filtered by status."""
        async with self._lock:
            tasks = self._read()
            if status:
                return [t for t in tasks if t["status"] == status]
            return tasks

    async def get_ready(self) -> list[dict]:
        """Return tasks whose dependencies are all done, ordered by priority."""
        async with self._lock:
            tasks = self._read()
            done_ids = {t["id"] for t in tasks if t["status"] == "done"}
            ready = [
                t for t in tasks
                if t["status"] == "open"
                and all(dep in done_ids for dep in t["dependencies"])
            ]
            ready.sort(key=lambda t: _PRIORITY_ORDER.get(t["priority"], 99))
            return ready

    async def increment_retry(self, task_id: str) -> int:
        """Increment retry_count under lock. Returns new count."""
        async with self._lock:
            tasks = self._read()
            for t in tasks:
                if t["id"] == task_id:
                    t["retry_count"] = t.get("retry_count", 0) + 1
                    t["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write(tasks)
                    return t["retry_count"]
            raise KeyError(f"Task {task_id} not found")
