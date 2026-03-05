# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is an autonomous investment agent (Python 3.11+, Poetry, SQLite). All commands are documented in `CLAUDE.md` and `README.md`.

### Quick reference

| Task | Command |
|------|---------|
| Install deps | `poetry install` |
| Run tests | `poetry run pytest -v` |
| Type check | `poetry run mypy src/` |
| DB migrate | `poetry run alembic upgrade head` |
| System status | `poetry run python -m src.orchestrator.main --status` |
| Dry-run cycle | `poetry run python -m src.orchestrator.main --dry-run` |

### Non-obvious caveats

- **Poetry PATH**: Poetry installs to `~/.local/bin`. The update script handles `pip install poetry` but if `poetry` is not on PATH, run `export PATH="$HOME/.local/bin:$PATH"`.
- **`.env` file required at project root**: Copy from `config/.env.example` if missing. Tests do **not** need API keys (in-memory SQLite), but `--dry-run` and live cycles do.
- **mypy exits non-zero**: The codebase has ~88 pre-existing mypy errors (type stub gaps for pandas/yfinance/ta/apscheduler, SQLAlchemy Column assignments). This is expected — do not treat mypy exit code 1 as a blocker.
- **Dry-run without API keys**: `--dry-run` completes with exit code 0 even without real API keys. It fetches yfinance data successfully but strategy synthesis fails (401). The JSON result shows `"status": "strategy_error"` — this is expected behavior with placeholder keys.
- **SQLite database location**: `data/investment_agent.db` is auto-created by Alembic migrations. No external DB server needed.
- **Screening cooldown**: After a dry-run, the 30 screened instruments get a 72h cooldown stamp. Subsequent dry-runs within 72h will screen different stocks from the seed universe. Delete the DB file to reset.
