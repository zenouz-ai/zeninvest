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
| Start dashboard backend | `poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000` (from project root) |

### Non-obvious caveats

- **Poetry PATH**: Poetry installs to `~/.local/bin`. The update script handles `pip install poetry` but if `poetry` is not on PATH, run `export PATH="$HOME/.local/bin:$PATH"`.
- **`.env` file required at project root**: Copy from `config/.env.example` if missing. Tests do **not** need API keys (in-memory SQLite), but `--dry-run` and live cycles do.
- **Test database isolation**: `conftest.py` sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1` so pytest uses in-memory SQLite; tests never touch `data/investment_agent.db`.
- **mypy exits non-zero**: The codebase has ~88 pre-existing mypy errors (type stub gaps for pandas/yfinance/ta/apscheduler, SQLAlchemy Column assignments). This is expected — do not treat mypy exit code 1 as a blocker.
- **Dry-run without API keys**: `--dry-run` completes with exit code 0 even without real API keys. It fetches yfinance data successfully but strategy synthesis fails (401). The JSON result shows `"status": "strategy_error"` — this is expected behavior with placeholder keys.
- **SQLite database location**: `data/investment_agent.db` is auto-created by Alembic migrations. No external DB server needed.
- **Finnhub timeouts in cloud VMs**: Finnhub API calls may time out in cloud/sandbox environments due to network latency. The pipeline handles this gracefully — analyst recommendations and insider sentiment will be missing but the cycle completes successfully. This does not block the pipeline.
- **Screening cooldown**: After a dry-run, the 30 screened instruments get a 72h cooldown stamp. Subsequent dry-runs within 72h will screen different stocks from the seed universe. Delete the DB file (`rm data/investment_agent.db && poetry run alembic upgrade head`) to reset.
- **Dashboard backend**: Run uvicorn from the **project root** (not from `dashboard/backend`). Otherwise you get `ModuleNotFoundError: No module named 'src'` because the project root is not on Python's path.
