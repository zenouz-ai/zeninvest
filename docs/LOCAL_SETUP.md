# Local Setup

This public mirror includes the code and docs needed for local development and
safe experimentation.

## Prerequisites

- Python `3.11+`
- Poetry
- Optional: Docker

## Install

```bash
git clone https://github.com/zenouz-ai/zeninvest.git
cd zeninvest
poetry install
cp config/.env.example .env
poetry run alembic upgrade head
```

## Useful Commands

```bash
poetry run pytest -q
poetry run mypy src/
poetry run python -m src.orchestrator.main --status
poetry run python -m src.orchestrator.main --dry-run
poetry run python -m dashboard.backend.server
```

## Notes

- Tests use in-memory SQLite and do not require live API keys.
- The `.env` file should remain local and untracked.
- Reverse proxy, TLS, and production deployment details are intentionally
  omitted from the public mirror.

## Docker

For a local multi-service setup:

```bash
docker compose up -d --build
docker compose logs -f investment-agent
docker compose logs -f dashboard
```
