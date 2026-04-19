# kandangkambing

A very basic Nanoclaw-based Discord bot that takes a feature request and turns it into a GitHub PR — with a PM agent to plan it, a Dev agent to implement it via Claude Code, and a QA agent to check the result before anything gets pushed.

You describe what you want. It opens a PR. You approve or reject it.

## What's inside

```
nanoclaw/          # the bot
  agents/          # PM, Dev, QA agents
  workflow/        # orchestration, job queue, approval gate
  tools/           # Claude Code CLI wrapper, Git, LLM router (Anthropic / OpenAI / Google)
  memory/          # SQLite conversation history, JSON task store, cost tracker
  safety/          # auth whitelist, rate limiter, daily budget guard
  config/          # settings, LLM routing table, per-agent prompts
docs/blog/         # 7-part series documenting how this was built
```

## Quick start

```bash
cd nanoclaw
pip install -r requirements.txt
cp .env.example .env        # fill in API keys
# edit config/settings.json — Discord channel IDs, allowed users, repo path
python bot.py
```

See [CLAUDE.md](CLAUDE.md) for full setup, Docker instructions, and how the agents fit together.

## Blog series

If you want to understand how it works before reading the code, start here:
https://dydanz.github.io/blog/building-nanoclaw

