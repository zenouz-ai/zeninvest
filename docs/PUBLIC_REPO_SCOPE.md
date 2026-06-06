# Public Repo Scope

`zenouz-ai/zeninvest` is a curated public mirror of the canonical
`KayvanNejabati/Investment-agent` repository.

## Included in the public repo

- application source code
- tests
- local setup instructions
- public CI and security workflows
- sanitized architecture and product documentation
- public branding assets used by the README and dashboard
- backtest configs and scenarios

## Intentionally omitted

- deployment runbooks
- private infrastructure details
- mirror token workflows
- operator-only operations docs
- internal launch planning and private process notes
- generated runtime outputs such as `data/`, `logs/`, `journals/`, and `backtests/results/`

## Top-level structure

- `src/` contains the agent runtime, orchestrator, scheduler, data models, backtesting, and research-only learning code.
- `dashboard/` contains the FastAPI operator API and React/Vite frontend.
- `docs/` contains public-safe architecture, setup, dashboard, research, roadmap, and workflow documentation.
- `config/` contains default settings and the `.env` example for local runs.
- `branding/` contains public ZenInvest visual identity assets.
- `tests/` contains the pytest suite, configured to use in-memory SQLite by default.
- `backtests/` contains reusable configs and scenarios; generated results stay local under `backtests/results/`.

## Why the split exists

The public repo is meant to be safe to browse, clone, and evaluate without
exposing infrastructure or operator procedures that belong only in the
canonical working repository.

## Contribution expectations

Public issues and pull requests are welcome, but some implementation and
release workflow detail lives only in the canonical repo. The public mirror is
updated through a curated export process rather than direct branch mirroring.
