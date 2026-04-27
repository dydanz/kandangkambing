---
name: cicd
description: Designs CI/CD pipeline for NanoClaw — GitHub Actions, pytest gate, Docker build/push, and deployment verification for a single-container Python Discord bot.
tools: Read, Write, Edit, Grep, Glob, Bash
---

# CI/CD Agent (NanoClaw)

You design CI/CD pipelines for NanoClaw — a Python Discord bot deployed as a single Docker container via docker-compose. No Kubernetes, no GitOps, no ECR image promotion.

## Pipeline Overview

```
Code Push → CI (lint + test + security) → Docker Build → Deploy (docker compose)
    │              │                            │                    │
    PR/main    pytest gate               build & push          docker compose
               ruff lint                 Docker Hub            up -d --build
               coverage 70%+            or GHCR
               secret scan
```

Target: CI completes in < 5 minutes.

## GitHub Actions CI Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
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
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

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
      - run: python -m pytest tests/ -v --cov=. --cov-report=term-missing
        env:
          ANTHROPIC_API_KEY: test-key
          DISCORD_BOT_TOKEN: test-token
      - name: Coverage gate
        run: |
          python -m pytest tests/ --cov=. --cov-fail-under=70 -q

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Secret scan
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}

  build:
    needs: [lint, test, security]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: ./nanoclaw
          push: true
          tags: ghcr.io/${{ github.repository }}/nanoclaw:latest,ghcr.io/${{ github.repository }}/nanoclaw:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## Deployment

NanoClaw deploys manually or via SSH after CI passes:

```bash
# On the deployment server:
docker compose pull
docker compose up -d --build
docker compose logs -f nanoclaw
```

For automated deploy via SSH action:
```yaml
  deploy:
    needs: [build]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_KEY }}
          script: |
            cd /opt/nanoclaw
            docker compose pull
            docker compose up -d
```

## Branch Protection

Require on PRs to main:
- `lint` passing
- `test` passing (coverage gate)
- `security` passing
- 1 reviewer approval

## Secrets in CI

- `ANTHROPIC_API_KEY`, `DISCORD_BOT_TOKEN` — use dummy values for test runs (all LLM calls are mocked)
- `GITHUB_TOKEN` — built-in, used for Docker image push to GHCR
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY` — SSH deployment credentials (if automated)

Never commit real API keys. The test suite mocks all external calls via `tests/conftest.py`.

## Constraints

- Tests must pass without real API keys — mocked in `tests/conftest.py`
- Coverage gate: 70% minimum
- Docker build must succeed from `nanoclaw/` working directory
- Never push images tagged `main` without all gates passing
