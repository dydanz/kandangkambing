# NanoClaw

Discord-based multi-agent coding system. PM, Dev, and QA agents collaborate to implement features via Claude Code, with human approval gates before any code is pushed.

## Setup

```bash
cd nanoclaw
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

1. Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

2. Edit `config/settings.json` with your Discord IDs and project paths.

## Run

```bash
python bot.py
```

## Test

```bash
pytest tests/ -v
```
