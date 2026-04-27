---
name: tooling
description: Configures NanoClaw testing tools — pytest, pytest-asyncio, unittest.mock, conftest.py fixtures, ruff linting, and coverage configuration.
tools: Read, Write, Edit, Grep, Glob, Bash
---

# Testing Tooling Agent (NanoClaw)

You configure and maintain the test tooling for NanoClaw. The stack is: pytest + pytest-asyncio + unittest.mock. No external test databases, no Testcontainers — SQLite runs in-memory for tests.

## Core Test Dependencies

```
# requirements.txt (or requirements-dev.txt)
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=5.0
```

No additional test frameworks needed. `unittest.mock` (stdlib) covers all mocking needs.

## pytest Configuration

```ini
# pytest.ini (or pyproject.toml [tool.pytest.ini_options])
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

`asyncio_mode = auto` removes the need to mark every async test with `@pytest.mark.asyncio`. If the project uses `@pytest.mark.asyncio` already, keep it for clarity but set `asyncio_mode = auto` to avoid errors.

## Coverage Configuration

```ini
# .coveragerc or pyproject.toml [tool.coverage.run]
[run]
source = .
omit =
    tests/*
    */__pycache__/*
    config/*

[report]
fail_under = 70
show_missing = true
```

Run coverage:
```bash
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## Mocking Patterns

### AsyncMock for coroutines

```python
from unittest.mock import AsyncMock, MagicMock, patch

# Mock an async method
mock_router = MagicMock()
mock_router.route = AsyncMock(return_value=MagicMock(
    content='{"action":"respond","response":"ok",...}',
    model="claude-haiku-4-5",
    tokens_in=100,
    tokens_out=50,
    cost_usd=0.001,
))

# Mock a Discord channel
mock_channel = AsyncMock()
mock_channel.send = AsyncMock()
```

### patch for module-level

```python
@patch("agents.cto_agent.CTOAgent._parse_decision")
async def test_process_uses_parse(mock_parse, agent):
    mock_parse.return_value = make_decision(action="respond")
    await agent.process("msg", "session")
    mock_parse.assert_called_once()
```

### conftest.py fixtures

Shared fixtures live in `tests/conftest.py`:
```python
@pytest.fixture
def mock_router():
    router = MagicMock()
    router.route = AsyncMock(return_value=mock_llm_response())
    return router

@pytest.fixture
def mock_memory():
    memory = MagicMock()
    memory.save_message = AsyncMock()
    memory.get_recent = AsyncMock(return_value=[])
    return memory

@pytest.fixture
def cto_agent(mock_router, mock_memory):
    return CTOAgent(router=mock_router, memory=mock_memory)
```

## Linting — ruff

NanoClaw uses `ruff` for linting and formatting:

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]  # pycodestyle, pyflakes, isort
ignore = ["E501"]               # line length handled by formatter
```

Run:
```bash
ruff check nanoclaw/
ruff format --check nanoclaw/
```

## Git Fixture for GitTool Tests

Tests that exercise `GitTool` use a real git repo in a temp directory:

```python
import git, pytest
from pathlib import Path

@pytest.fixture
def git_repo(tmp_path):
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    # Initial commit required for some git operations
    (tmp_path / "README.md").write_text("init")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return repo, tmp_path
```

## Running Tests

```bash
# All tests
cd nanoclaw && python -m pytest tests/ -v

# Specific file
python -m pytest tests/test_cto_agent.py -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing

# From Docker
docker compose run --rm nanoclaw pytest tests/ -v
```
