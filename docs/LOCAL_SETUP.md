# Local Setup and Live Run Guide

> Public-safe setup guide for local development, testing, dry runs, dashboard work, and optional broker-connected experimentation.

## Purpose

This document is the public mirror's main setup guide. It explains how to install dependencies, configure environment variables, initialize the database, run the core services, and validate the system locally without relying on private deployment infrastructure.

## Prerequisites

| Requirement | Minimum | Recommended | Notes |
|-------------|---------|-------------|-------|
| Python | 3.11 | 3.11 or 3.12 | Required by Poetry environment |
| Poetry | Latest | Latest | Dependency and virtualenv management |
| Disk space | 500 MB | 1 GB | For project, virtualenv, cache, and test artifacts |
| RAM | 4 GB | 8 GB | Helpful when dashboard, tests, and notebooks run together |
| Broker account | Practice / Demo | Practice / Demo | Use demo mode first; live trading requires deliberate operator review |
| API keys | Core model + data keys | Same | See environment variable section below |

## Installation

### 1. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

If `poetry` is not on `PATH`, add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Verify:

```bash
poetry --version
```

### 2. Install project dependencies

From the repository root:

```bash
poetry env use python3.11
poetry config virtualenvs.in-project true
poetry install --no-interaction
```

This installs runtime and development dependencies, including pytest, mypy, and notebook tooling.

### 3. Create a local `.env`

```bash
cp config/.env.example .env
```

The `.env` file is local-only and must never be committed.

### 4. Initialize the database

```bash
poetry run alembic upgrade head
```

This creates the SQLite database under `data/` with the tables used by the orchestrator, dashboard, reporting, and chat workflows.

## Environment Variables

The example file documents the full configuration surface. The main variables most operators care about are:

| Variable | Service | Purpose |
|----------|---------|---------|
| `T212_API_KEY` | Trading 212 | Broker authentication |
| `T212_API_SECRET` | Trading 212 | Broker authentication |
| `ANTHROPIC_API_KEY` | Anthropic | Strategy synthesis |
| `OPENAI_API_KEY` | OpenAI | Moderation, planner/composer, and selected chat flows |
| `GOOGLE_AI_API_KEY` | Google Gemini | Independent risk moderation |
| `FINNHUB_API_KEY` | Finnhub | Analyst recommendations, insider sentiment, macro/news enrichment |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | News sentiment and sector enrichment |

Additional optional variables cover Slack, SMTP, dashboard operator authentication, search providers, and advanced experimentation.

## Useful Commands

### Core validation

```bash
poetry run pytest -q
poetry run mypy src/
```

### Orchestrator

```bash
poetry run python -m src.orchestrator.main --status
poetry run python -m src.orchestrator.main --dry-run
poetry run python -m src.orchestrator.main --reset-peak
```

### Scheduler

```bash
poetry run python -m src.scheduler.scheduler
```

### Database migrations

```bash
poetry run alembic upgrade head
poetry run alembic current
```

## Tests and Validation

### Full test suite

```bash
poetry run pytest -v
```

### Targeted examples

```bash
poetry run pytest tests/test_risk_manager.py -v
poetry run pytest tests/test_execution.py -v
poetry run pytest tests/test_dashboard_auth.py -v
poetry run pytest tests/test_conversation_orchestrator.py -v
```

### Coverage

```bash
poetry run pytest --cov=src --cov-report=term-missing -v
```

## Important Local Behavior

- Tests use in-memory SQLite and do not touch the live `data/investment_agent.db`.
- A dry run can complete without valid live model credentials; broker-connected and research-heavy paths degrade or fail gracefully depending on feature area.
- The system defaults to practice-oriented workflows. Live trading should only be attempted after local validation, explicit credential review, and operator understanding of the risk posture.
- Some integrations depend on third-party rate limits or network conditions and may be slower or partially degraded in sandbox or VM environments.

## Dashboard Development

### Backend

Run from the project root so `src/` is importable:

```bash
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd dashboard/frontend
npm install
npm run dev
```

### Frontend tests

```bash
cd dashboard/frontend
npm test
```

### Frontend production build

```bash
cd dashboard/frontend
npm run build
```

## Docker

For a local multi-service setup:

```bash
docker compose up -d --build
docker compose logs -f investment-agent
docker compose logs -f dashboard
docker compose logs -f slack-listener
docker compose logs -f nginx
```

This public repo preserves the local/runtime Docker workflow but intentionally omits private deployment runbooks and infrastructure-specific production operations.

## Notebooks and Diagnostics

The repo includes notebooks and scripts for diagnostics, investigation, and backtesting support in the canonical repo. The public mirror focuses on the runnable application and public-safe docs, so some internal-only research or launch-planning materials are intentionally excluded.

## Troubleshooting

### `poetry: command not found`

Add Poetry to `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### `ModuleNotFoundError: No module named 'src'` when starting dashboard

Run the backend from the project root, not from inside `dashboard/backend`.

### Tests fail because of local state

Remove the local DB and re-run migrations:

```bash
rm -f data/investment_agent.db
poetry run alembic upgrade head
```

### Broker credentials are missing

Dry-run and many tests are still useful without broker credentials. Broker execution, stop maintenance, and live account workflows require the relevant Trading 212 environment variables.

## Public vs Private Boundary

This guide keeps everything required for local development and public understanding of the system. Private production ingress, TLS, VPS operations, and operator-only runbooks intentionally remain outside the public mirror.

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Dashboard](DASHBOARD.md)
- [Backtesting](BACKTESTING.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
- [Public Repo Scope](PUBLIC_REPO_SCOPE.md)
