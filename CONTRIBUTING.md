# Contributing to ZenInvest

Thank you for your interest in contributing to ZenInvest! This guide covers everything you need to get started.

## Prerequisites

- **Python 3.11+**
- **[Poetry](https://python-poetry.org/docs/#installation)** — dependency management
- **Docker** (optional) — for running the full stack locally

## Installation

```bash
# Clone the repo
git clone https://github.com/zenouz-ai/zeninvest.git
cd zeninvest

# Install dependencies
poetry install

# Copy the environment template
cp config/.env.example .env
# Edit .env with your API keys (not needed for running tests)

# Initialize the database
poetry run alembic upgrade head
```

## Running Tests

Tests use in-memory SQLite and require **no API keys** or external services:

```bash
poetry run pytest -v
```

The root `conftest.py` sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1` before any imports, so all tests automatically use an in-memory database. Tests never touch the production database at `data/investment_agent.db`.

## Type Checking

```bash
poetry run mypy src/
```

> **Note:** There are ~88 pre-existing mypy errors from type stub gaps in third-party packages (pandas, yfinance, ta, apscheduler, SQLAlchemy). These are expected and documented — do not treat a non-zero mypy exit code as a blocker.

## Code Style

- Follow the existing code style in the project
- Keep imports consistent with the codebase conventions (see below)
- Use type annotations for function signatures
- Write clear, descriptive variable and function names

## Import Rules

**Always use absolute imports.** Never use relative imports.

```python
# Correct
from src.agents.strategy.engine import StrategyEngine
from src.utils.config import get_settings
from src.data.database import get_session
from src.data.models import Instrument, Order

# Wrong — never do this
from ..strategy.engine import StrategyEngine
from .models import Instrument
```

This works because `pythonpath = ["."]` is set in `pyproject.toml`.

## Test Patterns

### In-memory SQLite fixture

All tests use in-memory SQLite. Use this pattern:

```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.module.path.get_session", return_value=db_session):
        yield
```

### Stubbing heavy dependencies

Stub external services (yfinance, httpx, broker APIs) with `unittest.mock.patch` or `sys.modules` mocks. Tests should never make real network calls.

## Adding Features

1. **Alembic migration** — If your change modifies the database schema, create a migration:
   ```bash
   poetry run alembic revision --autogenerate -m "description of change"
   ```

2. **Disable switch** — Every new feature must have a configuration toggle and fall back to current behaviour when disabled.

3. **Settings** — If your feature introduces new YAML keys, add corresponding properties to the `Settings` class in `src/utils/config.py`.

4. **Tests** — Write tests using the in-memory SQLite fixture pattern. Stub heavy dependencies.

## Documentation

All changes must update affected docs **in the same PR**. This is part of the definition of done.

Files to check on every change:

| File | Update when... |
|------|---------------|
| `README.md` | Any user-facing change: new CLI flags, output fields, pipeline steps, test count |
| `CLAUDE.md` | New architecture rules, models/columns, settings keys, patterns |
| `docs/ARCHITECTURE.md` | Pipeline flow changes, new components |
| `docs/GOVERNANCE.md` | Audit trail changes, risk rule changes, new kill switches |
| `docs/SOPHISTICATION_ROADMAP.md` | Features completed or added to pipeline |
| `dashboard/frontend/src/data/roadmap.ts` | Dashboard roadmap milestone status changes |

See `CLAUDE.md` for the full documentation maintenance table.

## Pull Request Process

1. **Fork** the repository
2. **Branch** from `main` — use a descriptive branch name (e.g. `feature/volume-signals`, `fix/stop-loss-cancel`)
3. **Implement** your changes following the guidelines above
4. **Test** — ensure `poetry run pytest -v` passes
5. **Open a PR** against `main`
6. **CI must pass** — the GitHub Actions workflow runs pytest and mypy automatically
7. **Review** — one approval required
8. **Merge** — squash merge into `main`

## PR Checklist

Before submitting, verify:

- [ ] All existing tests pass (`poetry run pytest -v`)
- [ ] New functionality is covered by tests
- [ ] Type annotations are correct (`poetry run mypy src/`)
- [ ] Affected docs updated (see table above)
- [ ] No API keys, secrets, or `.env` contents included
- [ ] New features have a disable switch
- [ ] Alembic migration added if schema changed

## Architecture Overview

For a full understanding of the system, see:

- **[CLAUDE.md](CLAUDE.md)** — Comprehensive AI context file covering architecture, key patterns, database models, and configuration
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — Pipeline flow, component interactions, and database schema
- **[docs/SOPHISTICATION_ROADMAP.md](docs/SOPHISTICATION_ROADMAP.md)** — Feature backlog and delivery status

## Questions?

- Browse existing issues and discussions on GitHub
- Check the docs linked above for architectural context
- Open an issue if you're unsure about an approach before investing time in implementation
