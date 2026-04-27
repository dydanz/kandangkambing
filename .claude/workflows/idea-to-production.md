# Workflow: Idea to Production

The end-to-end journey for a NanoClaw feature from idea to live Discord bot.

## Overview

```
Idea → Spec → Implementation Plan → Code (TDD) → PR → Merge → Deploy
  │       │           │                  │           │      │        │
brainstorm  design   writing-plans   TDD+tests   review  CI    docker
            doc                                                compose
⛔ No code written until spec is approved
```

## Phase 1: Discovery

**Goal:** Understand what to build before building it.

**Steps:**
1. Document the idea or user problem in 1-2 sentences
2. Invoke `superpowers:brainstorming` to explore the problem and options
3. Identify constraints: Does this require a new agent? New tool? New routing key?
4. Decide: is this a `respond` flow (inline answer) or an `execute` flow (new orchestrated behavior)?

**Exit criteria:**
- [ ] Problem statement clear
- [ ] Approach decided (new agent vs extend existing vs new tool)
- [ ] Out-of-scope explicitly noted

---

## Phase 2: Spec

**Goal:** Write a precise design document before touching code.

**Steps:**
1. Use `superpowers:brainstorming` to reach design consensus
2. Write design spec to `docs/specs/YYYY-MM-DD-[feature]-design.md`
3. Spec must include: what changes, what does NOT change, new data structures, error handling, testing plan
4. Get approval (review the spec file directly) before proceeding

**Exit criteria:**
- [ ] Spec saved and committed to `docs/specs/`
- [ ] All open questions resolved (no TBDs in the spec)
- [ ] "What does NOT change" section explicit (prevents scope creep)

---

## Phase 3: Implementation Plan

**Goal:** Break the spec into bite-sized, testable tasks.

**Steps:**
1. Invoke `superpowers:writing-plans` with the approved spec
2. Save plan to `docs/superpowers/plans/YYYY-MM-DD-[feature].md`
3. Each task must include: files to change, failing test to write, implementation code, passing test verification, commit command

**Key agents referenced in plans:**
- `python-architect` — agent/module structure decisions
- `concurrency` — async patterns, asyncio.gather
- `fault-tolerance` — LLM fallback, timeout handling
- `observability` — logging and cost tracking
- `testing-strategy` — what to test, mock patterns

**Exit criteria:**
- [ ] Plan saved and committed
- [ ] No placeholder tasks ("TBD", "implement later")
- [ ] All routing keys identified and noted

---

## Phase 4: Implementation

**Goal:** Build exactly what the spec says, test-first.

**Steps:**
1. Create git worktree: `superpowers:using-git-worktrees`
2. Execute tasks: `superpowers:subagent-driven-development`
3. Each task: write failing test → implement → pass test → commit
4. After all tasks: run full suite `python -m pytest tests/ -v`

**Key constraint:** Every LLM call must go through `LLMRouter`. Never call provider SDKs directly.

**Exit criteria:**
- [ ] All tasks completed
- [ ] `python -m pytest tests/ -v` — all passing
- [ ] Coverage gate holds: `pytest --cov-fail-under=70`
- [ ] Code reviewed (`/review-code`)

---

## Phase 5: PR and Merge

**Steps:**
1. Use `superpowers:finishing-a-development-branch` → choose Option 2 (Push + PR)
2. PR goes to main branch
3. CI must pass (lint + tests + build)
4. Merge after review

---

## Phase 6: Deploy

**Steps:**
1. After CI passes on main:
   ```bash
   docker compose pull && docker compose up -d
   ```
2. Verify: `@CTO status` responds in Discord
3. Check `docker compose logs nanoclaw` — no new ERRORs
4. Test the new feature manually in Discord

---

## Rules

- **No code without an approved spec** — spec first, always
- **No skipping tests** — CI must pass, coverage gate must hold
- **No direct LLM SDK calls** — always use `LLMRouter.route()`
- **No pushing to main/master** — PRs only, CI required
- **No secrets in git** — `.env` only, verified in `.gitignore`
