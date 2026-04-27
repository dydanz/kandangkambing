---
name: performance-chaos
description: NOT APPLICABLE — NanoClaw is a low-traffic Discord bot. Performance testing with k6/chaos engineering is not applicable at this scale.
---

NanoClaw is a low-traffic Discord bot (single-digit concurrent users). k6 load testing and chaos engineering are not applicable.

Performance concerns to watch:
- LLM API latency (monitor via `CostTracker` and Discord log channel)
- Git worktree creation time (visible in Discord progress updates)
- SQLite write contention (use `asyncio.Lock` in TaskStore)

If the bot becomes noticeably slow, add `asyncio.wait_for` timeouts and check for blocking I/O in async handlers. See `concurrency.md`.
