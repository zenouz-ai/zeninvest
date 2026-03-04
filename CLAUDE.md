# CLAUDE.md — AI Context for Investment Agent

This file provides context to AI assistants (Claude Code, Codex, Cursor, etc.) working on this repo.

## What This Project Is

Autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM pipeline. Runs on 12-hour cycles (07:00 + 19:00 UTC, Mon-Fri). Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Journal.

## Quick Commands

```bash
# Install
poetry install

# Database init/migrate
poetry run alembic upgrade head

# Run tests (in-memory SQLite, no API keys needed)
poetry run pytest -v

# Type checking
poetry run mypy src/

# Single cycle (dry run — no real trades)
poetry run python -m src.orchestrator.main --dry-run

# Single cycle (live on Practice account)
poetry run python -m src.orchestrator.main

# Continuous scheduler
poetry run python -m src.scheduler.scheduler

# System controls
poetry run python -m src.orchestrator.main --status
poetry run python -m src.orchestrator.main --pause
poetry run python -m src.orchestrator.main --resume
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
```

## Project Layout

```
src/
├── orchestrator/          # Main cycle loop (main.py) + state machine (ACTIVE/CAUTIOUS/HALTED)
├── agents/
│   ├── market_data/       # DataFetcher, FinnhubClient, AlphaVantageClient, universe screener, seed_universe
│   ├── strategy/          # StrategyEngine (Claude synthesis), momentum, mean_reversion, factor
│   ├── moderation/        # ModerationPanel — GPT-4o (skeptic) + Gemini (risk assessor) consensus
│   ├── risk/              # RiskManager — 9 hard rules with VETO power, no LLM involvement
│   ├── opportunity/       # OpportunityScorer + OpportunityOptimizer — UOV ranking, queueing, swap suggestions
│   ├── execution/         # OrderManager + T212Client — market orders, stop-loss, dedup
│   └── reporting/         # Trade journals (markdown per trade)
├── data/
│   ├── database.py        # SQLite engine + get_session() factory (WAL mode)
│   ├── models.py          # All SQLAlchemy ORM models
│   └── migrations/        # Alembic migrations
├── scheduler/             # APScheduler with persistent job store
└── utils/
    ├── config.py          # Settings singleton via get_settings()
    ├── cost_tracker.py    # Per-provider budget enforcement + graceful degradation
    └── logger.py          # Rich logging
config/
├── settings.yaml          # All tuneable parameters (trading, risk, strategy, universe, costs)
└── .env.example           # Required environment variables template
tests/                     # pytest — all use in-memory SQLite fixtures
```

## Key Patterns

### Imports — always absolute

```python
from src.agents.strategy.engine import StrategyEngine
from src.utils.config import get_settings
from src.data.database import get_session
from src.data.models import Instrument, Order
```

Never use relative imports. `pythonpath = ["."]` in pyproject.toml makes `src/` importable.

### Settings — singleton

```python
settings = get_settings()          # Global singleton, loaded once from settings.yaml + .env
settings.max_single_stock_pct      # Properties wrap dict access with type coercion
settings.screening_cooldown_hours  # Universe config
settings.t212_api_key              # Env var (raises EnvironmentError if missing)
```

### Database sessions

```python
session = get_session()  # New session from SessionLocal factory
try:
    # ... query / update ...
    session.commit()
except Exception:
    session.rollback()
finally:
    session.close()
```

### Test fixtures (in-memory SQLite)

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

## Ticker Format Gotcha

Trading 212 and yfinance use different ticker formats. **Always convert when crossing boundaries.**

| Context | Format | Example |
|---------|--------|---------|
| T212 API / database (`Instrument.ticker`) | `SYMBOL_COUNTRY_EQ` | `AAPL_US_EQ`, `BP._UK_EQ` |
| yfinance / indicators / fundamentals | Clean symbol | `AAPL`, `BP.L` |

```python
yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
```

Execution guardrail: strategy output may occasionally return plain symbols (`AAPL`, `NEM`, etc.). The orchestrator normalizes these to T212 instrument IDs (`AAPL_US_EQ`, `NEM_US_EQ`) via `stocks_data` and an instruments-table fallback before order placement.

## Architecture Rules

1. **Risk rules are deterministic Python** — never call an LLM from `RiskManager`. Its VETO is final.
2. **Defense in depth** — every trade passes Strategy → Moderation → Risk → Execution. Any layer can block.
3. **State machine** — ACTIVE → CAUTIOUS (>5% drawdown, no new positions) → HALTED (>15%, liquidate all). HALTED requires manual recovery.
4. **Screening cooldown** — `Instrument.last_screened_at` is stamped after each screen. Stocks within the cooldown window (default 72h) are excluded from `get_screened_universe()` to ensure broad rotation.
5. **Curated seed universe** — `seed_universe.py` contains ~160 well-known US equities. Used as fallback when instruments table lacks enriched data. Tickers that fail yfinance OHLCV fetch are flagged `data_available=False` and permanently excluded.
6. **Company profiles** — `longBusinessSummary` + `industry` from yfinance are persisted in the `Instrument` model and included in the Claude strategy prompt for qualitative reasoning.
7. **Cost degradation** — FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED. Budget per-provider per-day, plus monthly cap.
8. **Order dedup** — 5-minute window prevents double-execution of the same order.
9. **Stop-loss** — automatically placed after every BUY using Claude's `stop_loss_pct` (GTC validity).
10. **UOV optimizer guardrail** — UOV may reorder/queue BUYs, but it never directly triggers SELL/REDUCE. Strategy remains sell authority; Risk remains final veto.

## Environment Variables

All required, loaded from `.env` at project root:

```
T212_API_KEY          # Trading 212 (practice/demo)
T212_API_SECRET
ANTHROPIC_API_KEY     # Claude Sonnet (strategy)
OPENAI_API_KEY        # GPT-4o (moderation)
GOOGLE_AI_API_KEY     # Gemini Flash (moderation)
FINNHUB_API_KEY       # Analyst recs, insider sentiment
ALPHA_VANTAGE_API_KEY # AI news sentiment
```

## Database Models (src/data/models.py)

| Model | Table | Key Purpose |
|-------|-------|-------------|
| `SystemState` | `system_state` | State machine: ACTIVE/CAUTIOUS/HALTED, paused flag |
| `Instrument` | `instruments` | Cached T212 instruments with sector, industry, market_cap, business_summary, `data_available`, `last_screened_at` |
| `Order` | `orders` | Every order (filled, dry_run, failed) with dedup_key |
| `StrategyDecision` | `strategy_decisions` | Claude's proposals with conviction, reasoning |
| `ModerationLog` | `moderation_logs` | GPT-4o + Gemini verdicts with scores |
| `RiskDecision` | `risk_decisions` | Risk checks with triggered rules |
| `CostLog` | `cost_logs` | Per-LLM-call cost tracking |
| `MarketDataCache` | `market_data_cache` | OHLCV + fundamentals (12h TTL) |
| `PortfolioSnapshot` | `portfolio_snapshots` | End-of-cycle portfolio state |
| `OpportunityScoreSnapshot` | `opportunity_score_snapshots` | Per-cycle UOV components and final/ewma scores per ticker |
| `OpportunityQueue` | `opportunity_queue` | Active queued BUY opportunities awaiting execution |

## Configuration (config/settings.yaml)

Key tuneable values:

- **Trading**: `mode: practice`, `max_positions: 15`, `cash_floor_pct: 10`
- **Risk**: `max_single_stock_pct: 15`, `max_sector_pct: 35`, `halt_drawdown_pct: 15`
- **Strategy weights**: momentum `0.35`, mean_reversion `0.30`, factor `0.35`
- **Models**: `claude-sonnet-4-5-20250929` (strategy), `gpt-4o` + `gemini-2.5-flash` (moderation)
- **Universe**: `max_candidates: 30`, cap tiers 70/20/10% (large/mid/small), `screening_cooldown_hours: 72`
- **Cost**: Anthropic £1/day, OpenAI £0.75/day, Google £0.50/day, monthly cap £50
- **Opportunity**: `enabled`, `mode: shadow|active`, immediate/queue z-thresholds, queue TTL, swap delta, EWMA half-life, weighted feature map, stage penalties

## When Adding New Features

- Add Alembic migrations for schema changes: `poetry run alembic revision --autogenerate -m "description"`
- Add config properties to `Settings` class in `src/utils/config.py` if new YAML keys are introduced
- Write tests using in-memory SQLite fixtures — stub heavy deps (yfinance, httpx) with `sys.modules` mocks if needed
- The orchestrator pipeline is in `src/orchestrator/main.py:run_cycle()` — follow the existing phase pattern
- Consult `docs/SOPHISTICATION_ROADMAP.md` for the prioritised backlog and user story specifications
- All new features must have a disable switch and fall back to current behaviour
- No ML/RL technique adopted without literature review and clear expected impact documented

### Documentation maintenance (mandatory on every feature)

After any code change that adds, modifies, or removes functionality, **update all affected docs in the same PR**. This is not optional — treat docs as part of the definition of done.

Files to check on every feature:

| File | Update when... |
|------|---------------|
| `README.md` | Any user-facing change: new CLI flags, new output fields, new pipeline steps, test count changes |
| `CLAUDE.md` | New architecture rules, new models/columns, new settings keys, new patterns |
| `docs/ARCHITECTURE.md` | Pipeline flow changes, new database tables/columns, new component interactions |
| `docs/GOVERNANCE.md` | Audit trail changes (new logged fields, new tables), risk rule changes, new kill switches |
| `docs/PRESENTATION.md` | Major feature additions that change the project's story or metrics |
| `docs/LOCAL_LIVE_RUN.md` | New setup steps, new pre-flight checks, new CLI commands |
| `docs/DEPLOYMENT.md` | Infrastructure changes, new env vars, new Docker config, new systemd settings |
| `docs/DATA_RATIONALE.md` | New data sources, removed data points, changed data flow |
| `docs/SOPHISTICATION_ROADMAP.md` | Features completed (move to "done"), new user stories added |
| `docs/CHAT_INTERFACE_PROJECT.md` | Chat alerts / command interface scope, acceptance criteria, and rollout decisions |
| `docs/BACKTESTING_PROJECT_PLAN.md` | Backtesting scope, validation assumptions, and release-gate criteria |

**How to update:** After implementing a feature, scan each file above for sections that reference the changed area. Update inline — do not leave stale descriptions. Keep the same tone and depth as the existing content.

**Test count:** Update `README.md` status line (`N tests passing`) whenever tests are added or removed.

## Project Evolution Context

- **Current state:** POC v1.0 — deployed to VPS for live data collection on Trading 212 Practice
- **Development team:** Project Lead (PhD Maths, DS Manager), Claude Code Opus 4.6 (cloud, primary dev), Codex 5.3+ (local VS Code, secondary dev)
- **Principles:** Innovation, simplicity, elegance, transparency. No feature for technology's sake.
- **Key docs:** `docs/SOPHISTICATION_ROADMAP.md` (backlog), `docs/COMPETITIVE_ANALYSIS.md` (positioning)


## Near-term delivery focus (updated)

Current primary user stories for next-week implementation:
- **US-1.5 Chat Interface & Real-Time Trade Alerts** (`docs/CHAT_INTERFACE_PROJECT.md`)
- **US-5.1 Backtesting Engine foundations** (`docs/BACKTESTING_PROJECT_PLAN.md`)

When touching either track, keep `README.md`, `docs/ARCHITECTURE.md`, and `docs/SOPHISTICATION_ROADMAP.md` synchronized in the same PR.
