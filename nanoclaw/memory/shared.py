"""SharedMemory — conversation history persistence via SQLite."""
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path


_CONVERSATIONS_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    role        TEXT NOT NULL,
    agent       TEXT,
    content     TEXT NOT NULL,
    task_id     TEXT,
    model       TEXT,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_usd    REAL DEFAULT 0.0,
    metadata    TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversations_task_id   ON conversations(task_id);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_role      ON conversations(role);
"""


class SharedMemory:
    def __init__(self, db_path: str = "memory/conversations.db"):
        self.db_path = db_path
        self._initialized = False

    async def _ensure_db(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_CONVERSATIONS_DDL)
            await db.commit()
        self._initialized = True

    async def save_message(
        self,
        role: str,
        agent: str,
        content: str,
        task_id: str = None,
        model: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Insert a conversation row."""
        await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO conversations
                   (timestamp, role, agent, content, task_id, model,
                    tokens_in, tokens_out, cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, role, agent, content, task_id, model,
                 tokens_in, tokens_out, cost_usd),
            )
            await db.commit()

    async def get_recent(
        self,
        limit: int = 10,
        task_id: str = None,
    ) -> list[dict]:
        """Return most recent messages, optionally filtered by task_id."""
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if task_id:
                cursor = await db.execute(
                    """SELECT role, agent, content, timestamp
                       FROM conversations
                       WHERE task_id = ?
                       ORDER BY id DESC LIMIT ?""",
                    (task_id, limit),
                )
            else:
                cursor = await db.execute(
                    """SELECT role, agent, content, timestamp
                       FROM conversations
                       ORDER BY id DESC LIMIT ?""",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [
                {"role": r["role"], "agent": r["agent"],
                 "content": r["content"], "timestamp": r["timestamp"]}
                for r in reversed(rows)
            ]
