---
title: Multi-Bot Registry — CTO Listener + PM/SED/QAD Posting Clients
date: 2026-04-26
status: approved
---

# Multi-Bot Registry Design

## Problem

NanoClaw currently runs as a single Discord bot (`kambing`) that handles all
messages and posts all responses — planning output, implementation updates, QA
results, and CTO analysis — as the same identity. Users have no visual signal
about which agent is doing what.

Four specialised bot accounts have been created (`CTO`, `PM`, `SED`, `QAD`) and
their tokens are already in `.env`. They are valid and can post, but nothing uses
them yet.

---

## Goal

Make each agent stage visible in Discord as its own bot identity:

- `@CTO` is the entry point — receives all natural language messages, routes them,
  and posts analysis/clarify responses itself.
- `@PM` posts planning output.
- `@SED` posts implementation and PR updates.
- `@QAD` posts QA and code review results.

The existing `kambing` bot (`DISCORD_BOT_TOKEN`) is retired as the primary
listener. All agent logic, memory, safety, and orchestration remain unchanged.

---

## Architecture

```
User mentions @CTO
    ↓
CTO client (listener)
    ↓
bot._handle_message()
    ↓
CTOAgent.process()  →  CTODecision
    ↓
┌────────────────────────────────────────────────────────┐
│ decision.action                                        │
│  "execute"  → Orchestrator.handle(command,             │
│                 callback_factory=stage_callback_factory)│
│  "respond"  → cto_client.send(response)                │
│  "clarify"  → cto_client.send(question)                │
└────────────────────────────────────────────────────────┘
                    ↓ (execute path)
        stage_callback_factory(agent_name) → send_fn
            "pm"            → pm_client.send()
            "dev"           → sed_client.send()
            "qa"            → qad_client.send()
            "code_reviewer" → qad_client.send()
            default         → cto_client.send()
```

### What changes

| File | Change |
|------|--------|
| `tools/bot_registry.py` | **New** — `BotRegistry` class |
| `bot.py` | Add `BotRegistry` init; swap listener to CTO token; add `stage_callback_factory`; handle `bot_tokens` settings |
| `config/settings.py` | Add `bot_tokens: dict[str, str]` to `DiscordSettings` |
| `config/settings.json` | Add `discord.bot_tokens` mapping |
| `config/settings.docker.json` | Add `discord.bot_tokens` mapping |
| `tests/test_bot_registry.py` | **New** — unit tests for `BotRegistry` |
| `tests/test_bot_cto_integration.py` | Update patches to include `BotRegistry` |

### What does NOT change

`CTOAgent`, `PMAgent`, `DevAgent`, `QAAgent`, `CodeReviewerAgent`, `Orchestrator`,
`WorkflowEngine`, `JobQueue`, `SharedMemory`, `CostTracker`, safety layer — all untouched.

---

## BotRegistry (`tools/bot_registry.py`)

```python
@dataclass
class BotRegistry:
    cto: discord.Client    # listener + CTO responses
    pm:  discord.Client    # PM planning posts
    sed: discord.Client    # Dev/implementation posts
    qad: discord.Client    # QA + code review posts

    @classmethod
    async def create(cls, tokens: dict[str, str]) -> "BotRegistry":
        """
        Authenticate all posting clients (pm, sed, qad) via login-only.
        The CTO client is started normally via client.start() in bot.run().
        tokens: {"cto": "<token>", "pm": "<token>", "sed": "<token>", "qad": "<token>"}
        """

    def client_for(self, agent_name: str) -> discord.Client:
        """Return the posting client for a given agent name."""
        mapping = {"pm": self.pm, "dev": self.sed, "qa": self.qad,
                   "code_reviewer": self.qad}
        return mapping.get(agent_name, self.cto)
```

**Login strategy for posting clients:**
- `pm`, `sed`, `qad` clients call `await client.login(token)` only — no `client.run()` or
  event loop. This authenticates the HTTP session so `channel.send()` works without
  registering any Gateway connection.
- If a posting client fails to login (bad token, network), the failure is logged and
  `client_for()` falls back to `self.cto` for that agent. The workflow is never blocked.

---

## Stage-Aware Callback Factory

`bot.py` builds a callback factory instead of a single `progress_callback`:

```python
def _make_callback_factory(self, target_channel: discord.abc.Messageable):
    def factory(agent_name: str):
        client = self.registry.client_for(agent_name)
        # Find the channel object accessible to this client
        channel = client.get_channel(target_channel.id) or target_channel

        async def callback(msg: str):
            try:
                await channel.send(msg)
            except Exception as e:
                logger.warning("Failed to post as %s: %s", agent_name, e)
        return callback
    return factory
```

`Orchestrator.handle()` receives `callback_factory` instead of `progress_callback`.
The orchestrator passes `callback_factory(self.current_agent)` to each stage internally.

### Orchestrator change (minimal)

The only change to `orchestrator.py` is accepting an optional `callback_factory`
parameter alongside the existing `progress_callback`. If `callback_factory` is
provided, it takes precedence. This keeps backward compatibility with all existing
tests.

```python
async def handle(self, command: str, user_id: str,
                 thread_id: str | None = None,
                 progress_callback=None,        # existing — kept for compat
                 callback_factory=None,         # new
                 ) -> str:
```

---

## Settings Changes

### `config/settings.py`

```python
class DiscordSettings(BaseModel):
    allowed_user_ids: list[str]
    command_channel_id: str
    log_channel_id: str
    commits_channel_id: str
    bot_tokens: dict[str, str] = {}   # role → env var name
```

### `config/settings.json` and `config/settings.docker.json`

Add inside `"discord"`:

```json
"bot_tokens": {
  "cto": "DISCORD_CTO_TOKEN",
  "pm":  "DISCORD_PMO_TOKEN",
  "sed": "DISCORD_SED_TOKEN",
  "qad": "DISCORD_QAD_TOKEN"
}
```

`bot.py` resolves tokens at startup:

```python
tokens = {
    role: os.environ[env_var]
    for role, env_var in settings.discord.bot_tokens.items()
    if env_var in os.environ
}
self.registry = await BotRegistry.create(tokens)
```

---

## Bot Entry Point (`bot.py` changes)

### `__init__`
- Remove `self.client = discord.Client(...)` at the top level.
- `self.registry` is populated in `async_init()` (new coroutine called from `run()`).
- `self.client` becomes an alias for `self.registry.cto` after init.

### `run()`
```python
def run(self):
    token = os.environ.get("DISCORD_CTO_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("No CTO or bot token set")
        sys.exit(1)
    asyncio.run(self._async_run(token))

async def _async_run(self, token: str):
    self.registry = await BotRegistry.create(resolved_tokens)
    self.client = self.registry.cto
    self._register_events()
    await self.client.start(token)
```

### `_handle_message` — only change is callback factory
Replace:
```python
async def progress_callback(msg: str): ...
response = await self.orchestrator.handle(..., progress_callback=progress_callback)
```
With:
```python
callback_factory = self._make_callback_factory(target_channel)
response = await self.orchestrator.handle(..., callback_factory=callback_factory)
```

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Posting client login fails at startup | Logged as WARNING; `client_for()` returns `cto` as fallback |
| `channel.send()` fails on posting client | Caught in callback; logged as WARNING; workflow continues |
| `DISCORD_CTO_TOKEN` not set | Falls back to `DISCORD_BOT_TOKEN`; logs WARNING |
| All tokens missing | `sys.exit(1)` with clear error |
| CTOAgent LLM failure | Existing fallback unchanged — raw command to orchestrator |

---

## Message Appearance in Discord

For an `execute` flow, the thread will show:

```
[CTO]  NanoClaw: add health check endpoint    ← thread created by CTO
[PM]   📋 Planning: defining tasks for health check...
[PM]   ✅ Tasks ready: TASK-001 add /health route
[SED]  🔨 Implementing TASK-001...
[SED]  ✅ PR #43 opened: feat/add-health-endpoint
[QAD]  🧪 Running QA on PR #43...
[QAD]  ✅ QA passed — no critical findings
[CTO]  ✅ Done — PR #43 is ready for your review
```

---

## Testing

### `tests/test_bot_registry.py` (new)

```python
test_client_for_known_agents()          # pm→pm, dev→sed, qa→qad, code_reviewer→qad
test_client_for_unknown_falls_back_cto()
test_create_skips_missing_tokens()      # graceful when env var absent
test_create_falls_back_on_login_error() # discord.LoginFailure → cto fallback
```

### `tests/test_bot_cto_integration.py` (updated)

Add `patch("bot.BotRegistry")` to existing patch list. Assert `callback_factory` is
passed to `orchestrator.handle` instead of `progress_callback`.

---

## Out of Scope

- PM, SED, QAD receiving mentions or reacting to messages — they are posting-only
- `kambing` bot being decommissioned from the Developer Portal — just stop using it
- Per-bot rate limiting or cost tracking — all costs tracked under single `CostTracker`
- CTO research/documentation capability — covered in separate spec `2026-04-26-cto-research-docs-design.md`
