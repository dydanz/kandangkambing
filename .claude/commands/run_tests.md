# /run-tests

Runs the NanoClaw test suite, analyzes failures, and provides actionable fix guidance.

## When Invoked

If no scope is specified:

```
Which tests would you like to run?

1. All tests (full suite)
2. Specific module or file: [provide name]
3. Failed tests only (rerun last failures)
4. With coverage report
5. From Docker (docker compose run)

Or describe what you want to test.
```

## Test Execution

**Full suite:**
```bash
cd nanoclaw
python -m pytest tests/ -v
```

**With coverage:**
```bash
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

**Specific file:**
```bash
python -m pytest tests/test_cto_agent.py -v
```

**Specific test:**
```bash
python -m pytest tests/test_cto_agent.py::test_process_returns_respond_action -v -s
```

**From Docker:**
```bash
docker compose run --rm nanoclaw pytest tests/ -v
```

**Coverage gate check (CI-equivalent):**
```bash
python -m pytest tests/ --cov=. --cov-fail-under=70 -q
```

## Failure Analysis

For any test failure, analyze and report:

```markdown
## Test Run Summary
Date: YYYY-MM-DD HH:MM
Command: `python -m pytest tests/ -v`
Result: ❌ FAILED (N failures)

### Failed Tests

#### 1. tests/test_cto_agent.py::test_parse_decision_document_action
Error:
  AssertionError: expected doc_title == "OAuth Brief", got None

Root cause: _parse_decision() not populating doc_title when action=="document"
Fix: nanoclaw/agents/cto_agent.py:123 — add doc_title extraction from JSON

### Coverage Report
Module               Coverage  Concern
agents/cto_agent     82%
agents/base          71%
safety/budget_guard  68%       ⚠️ below 70% target
```

## Common Failure Patterns

**`AttributeError: 'MagicMock' object has no attribute 'route'`**
→ Mock setup incorrect. Use `AsyncMock` for coroutines:
```python
mock_router.route = AsyncMock(return_value=mock_response(...))
```

**`KeyError: 'research'` in settings loading**
→ New routing key in `settings.json` not added to `tests/conftest.py:SAMPLE_SETTINGS`

**`RuntimeError: no running event loop`**
→ Missing `@pytest.mark.asyncio` or `asyncio_mode = auto` not set in `pytest.ini`

**`sqlite3.OperationalError: database is locked`**
→ Two tests sharing a real SQLite file — use `:memory:` or `tmp_path` fixture

## Guidelines

- `-s` flag shows `print()` output and logging — useful for debugging
- Never modify test assertions to make tests pass — fix the code or test logic
- If a test is flaky (sometimes passes, sometimes fails), flag it with a `pytest.mark.skip` and a TODO
- Coverage below 70% overall is a concern — report which module is causing it
