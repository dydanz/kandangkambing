# Workflow: Feature Development Lifecycle

The day-to-day cycle for implementing a NanoClaw feature once the spec is approved.

## Overview

```
Spec Approved → Branch (worktree) → Implement (TDD) → Test → Review → PR → Merge
```

## Prerequisites

Before writing any code:
- [ ] Design spec written and approved in `docs/specs/YYYY-MM-DD-[feature]-design.md`
- [ ] Implementation plan written in `docs/superpowers/plans/YYYY-MM-DD-[feature].md`
- [ ] Git worktree created (use `superpowers:using-git-worktrees`)

## Step 1: Branch Setup

```bash
# Create a worktree for isolated development
git worktree add .worktrees/feat-[name] -b feat/[name]
cd .worktrees/feat-[name]/nanoclaw
pip install -r requirements.txt
python -m pytest tests/ -v   # verify baseline passes
```

## Step 2: Implement Following NanoClaw Patterns

**Order for new agents:**
1. Add routing key to `config/settings.json`, `config/settings.docker.json`, `tests/conftest.py:SAMPLE_SETTINGS`
2. Write frozen dataclass `{Name}Decision` in `agents/{name}_agent.py`
3. Write failing unit tests in `tests/test_{name}_agent.py`
4. Implement `BaseAgent` subclass with `async def process()`
5. Add prompt in `config/prompts/{name}_prompt.md`
6. Wire into `bot.py` and `orchestrator.py`
7. Add bot-level integration tests

**Order for new tools:**
1. Write failing tests for the tool
2. Implement the tool class
3. Inject into the relevant agent in `bot.py`

**At each step:**
```bash
python -m pytest tests/ -v --tb=short   # run full suite after each change
ruff check nanoclaw/                    # check for lint errors
```

## Step 3: Self-Review Checklist

Before opening a PR:

```
Agent/Tool:
  [ ] All new methods are async def
  [ ] LLM calls go through self.router.route() — no direct SDK calls
  [ ] New routing keys are in settings.json AND conftest.py:SAMPLE_SETTINGS
  [ ] Decision dataclass is frozen=True
  [ ] Fallback decision defined for LLM call failures
  [ ] Memory writes go through self.memory.save_message()

Tests:
  [ ] pytest tests/ -v — all pass
  [ ] pytest tests/ --cov=. --cov-fail-under=70 — coverage gate holds
  [ ] New agent has unit tests for all decision action types
  [ ] New integration tests for bot._handle_message() path

General:
  [ ] No debug prints left in code
  [ ] No TODO comments (convert to GitHub issues)
  [ ] No secrets in committed code
  [ ] PR description explains the why, not just the what
```

## Step 4: Code Review

Invoke `/review-code` for a self-review, then request team review.

**PR description format:**
```markdown
## What
[What was added or changed]

## Why
[Link to spec or describe the motivation]

## How
[Key technical decisions]

## Testing
[How to test manually — which Discord command to run]

## Checklist
- [ ] Tests added/updated
- [ ] Routing keys added to all config files
- [ ] No breaking changes to existing agents
```

## Step 5: Merge and Verify

After merging to main:
1. CI runs automatically → wait for green
2. If deploying: `docker compose pull && docker compose up -d`
3. Send `@CTO status` in Discord → verify response
4. Check `docker compose logs nanoclaw` for errors

## Handling Blockers

If you hit a blocker:
1. Document the specific obstacle clearly
2. Check `.claude/learnings.md` for related past findings
3. Use `/analyze-codebase` to understand the affected module
4. If the spec is wrong or incomplete: stop, update the spec, get approval, then continue
