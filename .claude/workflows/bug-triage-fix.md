# Workflow: Bug Triage & Fix

Process for identifying, investigating, and fixing bugs in NanoClaw.

## Severity Levels

| Severity | Definition | Fix Target |
|---|---|---|
| SEV1 - Critical | Bot offline, security breach, data loss | Hotfix < 4h |
| SEV2 - High | Core agent broken (CTO/PM/Dev/QA not responding) | Fix < 24h |
| SEV3 - Medium | Feature partially broken, workaround exists | Fix < 7 days |
| SEV4 - Low | Minor issue, edge case, cosmetic | Next session |

## Phase 1: Triage

When a bug is reported:

**Gather:**
1. Exact Discord command that triggered it
2. Expected behavior vs actual behavior
3. Error message from `docker compose logs nanoclaw`
4. Frequency: always / sometimes / once
5. When did this start? Was there a recent deploy?

**Check:**
```bash
docker compose logs --tail=100 nanoclaw | grep -E "ERROR|CRITICAL"
```

## Phase 2: Investigation

```
1. Reproduce locally
   - Run the bot locally with test settings
   - If you can't reproduce, add more logging and check prod logs

2. Find the root cause
   - Read the relevant agent's process() or the failing tool method
   - Use: git log, git blame, grep for the error message

3. Write a failing test FIRST
   - The test must fail with the current code
   - Tests live in tests/test_{module}.py
   - Use @pytest.mark.asyncio for async tests
   - Mock all LLM/Discord calls — see tests/conftest.py patterns

4. Fix the root cause, not the symptom
```

## Phase 3: Fix Implementation

```bash
git checkout -b fix/description
# implement fix
python -m pytest tests/ -v         # verify tests pass
python -m pytest tests/ --cov=. --cov-fail-under=70   # verify coverage
git commit -m "fix(scope): description"
git push origin fix/description
# open PR
```

**Fix checklist:**
- [ ] Failing test written first and now passes
- [ ] All existing tests still pass
- [ ] Root cause fixed (not symptom)
- [ ] No new linting errors (`ruff check nanoclaw/`)
- [ ] If LLM routing key was missing: added to `settings.json` AND `tests/conftest.py:SAMPLE_SETTINGS`

## Phase 4: Verification

```
Automated:
  [ ] pytest tests/ -v — all pass
  [ ] coverage gate holds (≥ 70%)

Local manual:
  [ ] Bug cannot be reproduced with original repro steps
  [ ] Adjacent commands (status, cost, etc.) still work

Post-deploy:
  [ ] Bot comes back online
  [ ] @CTO status responds
  [ ] docker compose logs shows no new ERRORs
```

## Guidelines

- Never fix a bug without writing a failing test first — the test proves the bug existed
- Root cause analysis means "why did the code behave this way" — not "the code was wrong"
- For LLM-related bugs: add the failing JSON fixture to the test to reproduce the exact parse error
- Document non-obvious findings in `.claude/learnings.md`
