---
name: ci-testing
description: Integrates NanoClaw tests into GitHub Actions CI — pytest with coverage gate, caching, parallel execution, and failure reporting.
tools: Read, Write, Edit, Grep, Glob, Bash
---

# CI Testing Agent (NanoClaw)

You integrate NanoClaw's pytest suite into GitHub Actions CI. Target: tests complete in < 3 minutes.

## CI Test Job

```yaml
# .github/workflows/ci.yml (test job)
test:
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: nanoclaw
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: pip
    - run: pip install -r requirements.txt

    - name: Run tests with coverage
      run: python -m pytest tests/ -v --cov=. --cov-report=xml --cov-report=term-missing
      env:
        ANTHROPIC_API_KEY: test-key
        DISCORD_BOT_TOKEN: test-token

    - name: Coverage gate (70% minimum)
      run: python -m pytest tests/ --cov=. --cov-fail-under=70 -q

    - name: Upload coverage report
      uses: codecov/codecov-action@v4
      with:
        files: nanoclaw/coverage.xml
      if: always()
```

## Caching Strategy

`actions/setup-python` with `cache: pip` caches the pip install. This requires a `requirements.txt` file that doesn't change between runs.

If install time is > 60s, split into:
```yaml
- run: pip install --cache-dir ~/.cache/pip -r requirements.txt
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('nanoclaw/requirements.txt') }}
```

## Test Parallelization

NanoClaw's test suite is fast enough to run serially (< 3 min). If it grows:

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run in parallel (4 workers)
python -m pytest tests/ -n 4
```

Caution: parallel tests must be fully isolated — no shared mutable state, no shared SQLite files.

## Failure Analysis

When CI fails:
1. Check the pytest output for the failing test name
2. Reproduce locally: `python -m pytest tests/test_failing.py::test_name -v -s`
3. Add `-s` to see `print()` output and logging
4. Check if the failure is a missing mock (look for `AttributeError` on `AsyncMock`)
5. Check if `SAMPLE_SETTINGS` is missing a routing key that `settings.json` has

## Coverage Gate Exceptions

If a new module intentionally has low coverage (e.g., a thin wrapper around discord.py), add it to `.coveragerc` omit list rather than weakening the global gate:

```ini
[coverage:run]
omit =
    tests/*
    nanoclaw/bot.py   # Discord event wiring — tested via integration tests
```

## Branch Protection

Require the `test` job to pass before any PR can merge. Configure in GitHub: Settings → Branches → Branch protection rules → Require status checks: `test`.
