# ZenInvest

[![CI](https://github.com/zenouz-ai/zeninvest/actions/workflows/ci.yml/badge.svg)](https://github.com/zenouz-ai/zeninvest/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="branding/ZenInvest.png" alt="ZenInvest" width="820" />
</p>

**ZenInvest is a proof-of-concept autonomous investment research and execution system built around a multi-LLM committee with deterministic trading guardrails.**

This public repository is a **curated mirror** of the canonical development
repo. It includes the application code, tests, public-safe workflows, and
sanitized documentation needed to understand and run the project locally.
Operator runbooks, deployment specifics, and private infrastructure details are
intentionally omitted.

## Important Notes

- This project is a **research / engineering proof of concept**, not an
  investment product.
- Nothing in this repository is financial advice.
- Live trading requires your own credentials, infrastructure choices, and
  operator judgment.
- Public releases are synchronized from the canonical repo rather than
  developed directly in this mirror.

## How It Works

```text
Orchestrator
  ├── Market Data Agent    → market data, fundamentals, macro context
  ├── Universe Screener    → candidate discovery
  ├── Strategy Agent       → thesis generation and sizing suggestions
  ├── Moderation Panel     → adversarial review
  ├── Risk Agent           → deterministic veto rules
  ├── Opportunity Agent    → queueing and prioritisation
  ├── Execution Agent      → broker integration workflows
  ├── Refresh Lane         → broker sync and stop maintenance
  └── Journal & Reporting  → runs, orders, outcomes, and audit trail
```

## Quick Start

### Prerequisites

- Python `3.11+`
- [Poetry](https://python-poetry.org/docs/#installation)
- A project-root `.env` copied from `config/.env.example`

### Install

```bash
git clone https://github.com/zenouz-ai/zeninvest.git
cd zeninvest
poetry install
cp config/.env.example .env
poetry run alembic upgrade head
```

### Run a Dry Cycle

```bash
poetry run python -m src.orchestrator.main --dry-run
```

### Run Tests

```bash
poetry run pytest -q
```

## Public Repo Scope

The public repo keeps:

- source code
- tests
- public CI and security workflows
- local setup and architecture docs
- sanitized dashboard, research, and workflow docs

The public repo does **not** include:

- private deployment runbooks
- organization-specific infrastructure details
- mirror token workflows
- internal launch planning or operator-only operations docs

See [Public Repo Scope](docs/PUBLIC_REPO_SCOPE.md).

## Documentation

- [Local Setup](docs/LOCAL_SETUP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Dashboard](docs/DASHBOARD.md)
- [Agentic Research](docs/AGENTIC_RESEARCH.md)
- [Conversational Trading Workflow](docs/CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Backtesting](docs/BACKTESTING.md)
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md)
- [Public Repo Scope](docs/PUBLIC_REPO_SCOPE.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and contribution guidance.

## Security

See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.
