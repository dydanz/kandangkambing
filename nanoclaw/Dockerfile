FROM python:3.11-slim

# System deps: git, gh CLI, Node.js (for Claude Code CLI), curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    gnupg \
    openssh-client \
    nodejs \
    npm \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Writable dirs for SQLite and logs
RUN mkdir -p memory logs

# Run from /app so relative paths (memory/*.db, config/settings.json) resolve correctly
CMD ["python", "bot.py"]
