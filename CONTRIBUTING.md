# Contributing to ZenInvest

Thanks for your interest in ZenInvest.

This public repository is a curated mirror of the canonical development repo.
Issues and pull requests are still useful here, but some private operational
materials are intentionally omitted from the public tree.

## Prerequisites

- Python `3.11+`
- [Poetry](https://python-poetry.org/docs/#installation)
- Docker is optional for local experimentation

## Local Setup

```bash
git clone https://github.com/zenouz-ai/zeninvest.git
cd zeninvest
poetry install
cp config/.env.example .env
poetry run alembic upgrade head
```

Tests do not require live API keys. The in-memory SQLite test configuration is
enabled automatically by `conftest.py`.

## Common Commands

```bash
poetry run pytest -q
poetry run mypy src/
poetry run python -m src.orchestrator.main --dry-run
```

## Conventions

- Use absolute imports from `src.*`
- Keep new features behind an explicit config toggle where practical
- Update public-facing docs in the same PR when behavior changes
- Avoid committing secrets, `.env` contents, local DBs, or generated artifacts

## Pull Requests

Before opening a PR:

- make sure tests pass locally
- add or update tests for behavior changes
- update affected docs
- call out schema or migration changes explicitly

## Public Repo Scope

This repo includes public-safe code and docs only. Deployment runbooks,
organization-specific operations docs, and private mirror mechanics are omitted
from the public tree by design.

See [docs/PUBLIC_REPO_SCOPE.md](docs/PUBLIC_REPO_SCOPE.md) for the public/private split.
