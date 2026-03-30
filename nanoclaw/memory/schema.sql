-- NanoClaw Memory Layer DDL
-- conversations.db
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    role        TEXT NOT NULL,       -- 'user','pm','dev','qa','system'
    agent       TEXT,                -- which agent produced this
    content     TEXT NOT NULL,
    task_id     TEXT,                -- FK to tasks.json id
    model       TEXT,                -- model used for this call
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_usd    REAL DEFAULT 0.0,
    metadata    TEXT                 -- JSON blob for extra info
);

CREATE INDEX IF NOT EXISTS idx_conversations_task_id   ON conversations(task_id);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_role      ON conversations(role);

-- cost_log table (in costs.db)
CREATE TABLE IF NOT EXISTS cost_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    session_id  TEXT NOT NULL,       -- groups all calls in one workflow run
    task_id     TEXT,
    agent       TEXT NOT NULL,       -- 'pm','dev','qa','router'
    provider    TEXT NOT NULL,       -- 'anthropic','openai','google'
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    cost_usd    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cost_session   ON cost_log(session_id);
CREATE INDEX IF NOT EXISTS idx_cost_task      ON cost_log(task_id);
CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_log(timestamp);
