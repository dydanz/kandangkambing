# /analyze-codebase

Analyzes the NanoClaw codebase to understand its structure, patterns, and health. Use before planning any feature or refactor.

## When Invoked

If no specific focus area is provided, present:

```
What would you like to analyze?

1. Full codebase overview (architecture, agents, data flows)
2. Agent layer (BaseAgent pattern, decision types, LLM routing)
3. Bot and orchestrator (Discord event wiring, command routing)
4. Tools layer (GitTool, LLMRouter, BotRegistry, ClaudeCodeTool)
5. Safety layer (Auth, RateLimiter, BudgetGuard)
6. Tests (coverage, mock patterns, conftest fixtures)
7. Specific module: [provide name]

Reply with a number or describe what you'd like to understand.
```

## Analysis Process

### Step 1: Discovery

Read key entry points first:
- `nanoclaw/bot.py` — Discord client, event wiring, BotRegistry
- `nanoclaw/orchestrator.py` — command routing
- `nanoclaw/agents/` — all agent files
- `nanoclaw/config/settings.json` — LLM routing and channel config
- `nanoclaw/tests/conftest.py` — SAMPLE_SETTINGS and fixtures

Use `git log --name-only -20` to identify the most recently changed files.

### Step 2: Pattern Analysis

For each discovered component:
- Is it following the BaseAgent pattern? (subclass, frozen dataclass decision, async process())
- Does it have corresponding tests?
- Are LLM calls going through LLMRouter (not direct SDK calls)?
- Is the routing key registered in settings.json AND conftest.py?

### Step 3: Synthesis

Produce a structured analysis:

```markdown
## Codebase Analysis: NanoClaw
Date: YYYY-MM-DD
Commit: [current git hash]

### Architecture Summary
[2-3 sentence overview]

### Agent Layer
- Agents present: [list]
- Decision types: [list]
- LLM routing keys: [list — cross-check against settings.json]
- Observations: [file:line references]
- Gaps: [missing tests, missing routing keys, pattern deviations]

### Bot & Orchestrator
- Discord clients: [CTO/PM/SED/QAD vs single bot]
- Command routing: [how commands reach agents]
- Observations: [file:line references]

### Tools
- GitTool: [push guard active? write_and_commit present?]
- LLMRouter: [providers configured, fallback chain]
- BotRegistry: [all 4 clients wired?]

### Safety
- Auth: [allowlist populated?]
- BudgetGuard: [daily limit set?]
- RateLimiter: [per-minute limit set?]

### Tests
- Coverage: [% if available]
- Mock pattern: [AsyncMock / MagicMock — consistent?]
- SAMPLE_SETTINGS: [matches settings.json routing keys?]
- Gaps: [untested agents, missing edge cases]

### Priority Recommendations
1. [Most critical gap]
2. [Second priority]
3. [Third priority]
```

## Guidelines

- Reference specific file paths and line numbers in findings
- Cross-check `config/settings.json` routing keys against `tests/conftest.py:SAMPLE_SETTINGS`
- Do not change any code during analysis — read-only
- Flag any place where agent code calls an LLM SDK directly (bypassing LLMRouter)
