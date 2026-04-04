"""CostTracker — LLM cost logging and rollup via SQLite."""
import json
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path


_COST_DDL = """
CREATE TABLE IF NOT EXISTS cost_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    task_id     TEXT,
    agent       TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    cost_usd    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_session   ON cost_log(session_id);
CREATE INDEX IF NOT EXISTS idx_cost_task      ON cost_log(task_id);
CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_log(timestamp);
"""


class CostTracker:
    def __init__(
        self,
        db_path: str = "memory/costs.db",
        pricing_path: str = "config/pricing.json",
    ):
        self.db_path = db_path
        self._pricing = self._load_pricing(pricing_path)
        self._initialized = False

    @staticmethod
    def _load_pricing(path: str) -> dict:
        with open(path) as f:
            return json.load(f)

    async def _ensure_db(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_COST_DDL)
            await db.commit()
        self._initialized = True

    def _calc_cost(self, provider: str, model: str,
                   tokens_in: int, tokens_out: int) -> float:
        """Calculate USD cost from the pricing table. Per-million-token rates."""
        provider_prices = self._pricing.get(provider, {})
        model_prices = provider_prices.get(model)
        if not model_prices:
            return 0.0
        cost = (tokens_in * model_prices["in"] / 1_000_000
                + tokens_out * model_prices["out"] / 1_000_000)
        return round(cost, 6)

    async def log(
        self,
        session_id: str,
        task_id: str,
        agent: str,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> float:
        """Log a call. Returns cost_usd calculated from pricing table."""
        await self._ensure_db()
        cost = self._calc_cost(provider, model, tokens_in, tokens_out)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO cost_log
                   (timestamp, session_id, task_id, agent, provider, model,
                    tokens_in, tokens_out, cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, session_id, task_id, agent, provider, model,
                 tokens_in, tokens_out, cost),
            )
            await db.commit()
        return cost

    async def daily_total(self, date: str = None) -> float:
        """Return total USD spent today (or given date YYYY-MM-DD)."""
        await self._ensure_db()
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT COALESCE(SUM(cost_usd), 0.0)
                   FROM cost_log
                   WHERE timestamp LIKE ?""",
                (f"{date}%",),
            )
            row = await cursor.fetchone()
            return row[0]

    async def task_total(self, task_id: str) -> float:
        """Return total USD spent on a task."""
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT COALESCE(SUM(cost_usd), 0.0)
                   FROM cost_log WHERE task_id = ?""",
                (task_id,),
            )
            row = await cursor.fetchone()
            return row[0]

    async def session_summary(self, session_id: str) -> dict:
        """Return per-model breakdown for a session."""
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT provider, model,
                          SUM(tokens_in) as total_in,
                          SUM(tokens_out) as total_out,
                          SUM(cost_usd) as total_cost
                   FROM cost_log
                   WHERE session_id = ?
                   GROUP BY provider, model""",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return {
                "session_id": session_id,
                "models": [
                    {
                        "provider": r["provider"],
                        "model": r["model"],
                        "tokens_in": r["total_in"],
                        "tokens_out": r["total_out"],
                        "cost_usd": r["total_cost"],
                    }
                    for r in rows
                ],
                "total_cost": sum(r["total_cost"] for r in rows),
            }
