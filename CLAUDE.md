# CLAUDE.md — AI Context for Investment Agent

This file provides context to AI assistants (Claude Code, Codex, Cursor, etc.) working on this repo.

## What This Project Is

Autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM pipeline. Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Journal.

**Scheduling architecture:** Configurable via `cycle_frequency` in `config/settings.yaml`:
- **intraday** (default): 3 cycles at 08:00, 12:00, 16:00 UTC — more timely decisions, uses deferred Finnhub/AV and tiered caching to stay within API limits.
- **standard**: 2 cycles at 07:00, 19:00 UTC — original 12-hour cadence.
Autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM pipeline. Runs on 12-hour cycles (07:00 + 19:00 UTC, Mon-Fri). Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Order Management (stop-loss reassessment, trailing stops, limit orders) → Journal.

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
poetry run python -m src.orchestrator.main --performance
poetry run python -m src.orchestrator.main --dashboard
poetry run python -m src.orchestrator.main --pause
poetry run python -m src.orchestrator.main --resume
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
poetry run python -m src.orchestrator.main --report
# Backtesting (real data: fetches yfinance if data/backtest/ empty, caches to CSV)
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
```

## Project Layout

```
src/
├── orchestrator/          # Main cycle loop (main.py) + state machine (ACTIVE/CAUTIOUS/HALTED)
├── agents/
│   ├── market_data/       # DataFetcher, FinnhubClient, AlphaVantageClient, macro_intelligence, universe screener, seed_universe
│   ├── strategy/          # StrategyEngine (Claude synthesis), momentum, mean_reversion, factor
│   ├── moderation/        # ModerationPanel — GPT-4o (skeptic) + Gemini (risk assessor) consensus
│   ├── risk/              # RiskManager — 9 hard rules with VETO power, no LLM involvement
│   ├── opportunity/       # OpportunityScorer + OpportunityOptimizer — UOV ranking, queueing, swap suggestions
│   ├── execution/         # OrderManager + T212Client + StopLossManager — market/limit/stop orders, trailing stops, dedup
│   ├── notifications/     # NotificationService + Slack/Email providers + formatters + command gateway scaffold
│   └── reporting/         # Trade journals, daily/weekly reports, performance tracker, trade outcome tracker
├── data/
│   ├── database.py        # SQLite engine + get_session() factory (WAL mode)
│   ├── models.py          # All SQLAlchemy ORM models
│   └── migrations/        # Alembic migrations
├── scheduler/             # APScheduler: analysis cycles from cycle_times_utc, daily snapshot, weekly report, instrument refresh
├── backtesting/           # Engine, paper broker, io (load/fetch yfinance + CSV cache), metrics, walk-forward, promotion report
└── utils/
    ├── config.py          # Settings singleton via get_settings()
    ├── cost_tracker.py    # Per-provider budget enforcement + graceful degradation
    └── logger.py          # Rich logging
config/
├── settings.yaml          # All tuneable parameters (trading, risk, strategy, universe, costs, notifications)
└── .env.example           # Environment variables template (required core API keys + optional notification keys)
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
5a. **Deferred Finnhub/AV (intraday)** — When `cycle_frequency: intraday`, screening uses `get_stock_analysis_lite` (yfinance only). Finnhub and Alpha Vantage are fetched only for `positions ∪ top_tickers` (active-review tickers), with `NewsSentimentCache` lookup first.
6. **Company profiles** — `longBusinessSummary` + `industry` from yfinance are persisted in the `Instrument` model and included in the Claude strategy prompt for qualitative reasoning.
7. **Cost degradation** — FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED. Budget per-provider per-day, plus monthly cap.
8. **Order dedup** — 5-minute window prevents double-execution of the same order.
9. **Stop-loss** — automatically placed after every BUY using Claude's `stop_loss_pct` (GTC validity).
10. **UOV optimizer guardrail** — UOV may reorder/queue BUYs, but it never directly triggers SELL/REDUCE. Strategy remains sell authority; Risk remains final veto.
11. **Notification fail-open** — alert delivery failures (Slack/Email) must never block trade execution.
12. **Intelligent order management** — `StopLossManager` runs after execution each cycle. Three capabilities:
    - **ATR-based stop reassessment**: Recalculates stops using 14-day ATR × configurable multiplier, clamped to [min, max] distance. By default only tightens (never widens).
    - **Software trailing stops**: Tracks high-water mark per position. Ratchets stop up as price rises. Implemented by cancel + replace since T212 has no native trailing stop.
    - **Limit dip-buy orders**: When strategy outputs `entry_type: "limit_dip"`, places limit BUY below current price instead of market order. Offset % configurable globally or per-decision.
    - All adjustments logged to `stop_loss_adjustments` table and emitted as `order_adjustment` Slack notifications.

## Scheduling Architecture

The scheduler (`src/scheduler/scheduler.py`) creates one cron job per entry in `settings.cycle_times_utc`. Cycle times are resolved from `cycle_frequency`:

| `cycle_frequency` | `cycle_times_utc` | `cycle_hours` | Use case |
|------------------|------------------|---------------|----------|
| `intraday` | 08:00, 12:00, 16:00 UTC | 4 | 3 runs during market hours; deferred Finnhub/AV + tiered cache |
| `standard` | 07:00, 19:00 UTC | 12 | Original 2-cycle cadence |

Other scheduled jobs (unchanged): daily snapshot 21:30 UTC, weekly report Fri 22:00 UTC, instrument refresh Sun 12:00 UTC.

## Environment Variables

Required core keys (loaded from `.env` at project root):

```
T212_API_KEY          # Trading 212 (practice/demo)
T212_API_SECRET
ANTHROPIC_API_KEY     # Claude Sonnet (strategy)
OPENAI_API_KEY        # GPT-4o (moderation)
GOOGLE_AI_API_KEY     # Gemini Flash (moderation)
FINNHUB_API_KEY       # Analyst recs, insider sentiment
ALPHA_VANTAGE_API_KEY # AI news sentiment
```

Optional notification keys:

```
SLACK_WEBHOOK_URL
ALERT_EMAIL_FROM
ALERT_EMAIL_TO
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASS
SMTP_USE_TLS
```

### Chat notifications rollout notes (US-1.5)

- Notification service is fail-open by design: provider errors must not block cycle execution.
- Current default routing in `config/settings.yaml`:
  - `trade_instruction_approved` -> `["slack"]`
  - `trade_execution_result` -> `["slack", "email"]`
  - `cycle_run_summary` -> `["slack"]`
  - `state_transition` -> `["slack", "email"]`
  - `critical_cycle_failure` -> `["slack", "email"]`
  - `order_adjustment` -> `["slack"]`
  - `include_dry_run_alerts: false`
- SendGrid SMTP convention:
  - `SMTP_HOST=smtp.sendgrid.net`
  - `SMTP_PORT=587`
  - `SMTP_USER=apikey`
  - `SMTP_USE_TLS=true`
- Known delivery gotcha observed during rollout:
  - `notification_logs.status='sent'` can still correspond to inbox delays if provider returns deferred responses.
  - Example seen: Gmail deferral `421 4.7.32` for one recipient; resolved by using a different recipient + checking SendGrid Email Logs.

### Notification module structure (`src/agents/notifications/`)

- **types.py** — `NotificationEvent`, `NotificationMessage`, `TradeInstructionPayload`, `TradeExecutionPayload`, `NotificationError`
- **formatters.py** — Channel-specific rendering (`render_event` → Slack/Email). Trade/queued messages include ticker, action, quantity (or "queued"), committee summary (Moderation=X | Risk=Y), reasoning excerpt, and stage reason for queued/filtered decisions (e.g. "Queued by UOV optimizer (capacity/threshold gating)").
- **service.py** — `NotificationService` with `emit_*` methods. Fail-open: all exceptions caught, logged with `exc_info`, and never propagated. Retries with backoff; failed attempts recorded in `notification_logs`.
- **providers/** — Slack webhook, SMTP email. Providers implement `send(subject, body)` and raise on failure.
- **Event types**: `trade_instruction_approved`, `trade_execution_result`, `cycle_run_summary`, `state_transition`, `critical_cycle_failure`

### Macro intelligence module (`src/agents/market_data/macro_intelligence.py`)

Gathers macro-level market intelligence to inform trading decisions:

1. **Sector-level sentiment and trend** — Alpha Vantage SECTOR API (1 call) returns real-time S&P 500 sector performance. When AV fails (rate limit, error), fallback to yfinance SPDR ETFs (XLK, XLV, etc.). Sectors underperforming on multiple horizons are flagged as "underperform" for headwind detection.
2. **Key economic news** — Finnhub `/news` (category=general) free tier: Fed, tariffs, earnings, inflation headlines. Used for timing context (e.g. earnings season flag).
3. **Committee decision integration** — `get_sector_headwind(macro_intel, yf_sector)` returns a message when a sector is underperforming, enabling moderators to flag "fundamentally strong but sector headwind — defer buy"

**Data flow**:
- `get_macro_data()` in DataFetcher now includes `macro_intelligence` (cached 4h via `NewsSentimentCache`).
- Strategy prompt receives sector summary + economic highlights in news section.
- Moderation context receives `sector_headwind`, `economic_highlights`, `sector_summary` in Market Conditions.

**Config**: `data_providers.macro_intelligence_enabled: true`, `cache_ttl_hours.macro_intelligence: 4`

**Sector mapping**: yfinance sectors (Technology, Healthcare, etc.) → Alpha Vantage (Information Technology, Health Care, etc.) via `YF_TO_AV_SECTOR`.

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
| `ApiLog` | `api_logs` | External API call audit trail (T212, Finnhub, Alpha Vantage) |
| `NotificationLog` | `notification_logs` | Outbound alert audit trail (sent/failed/skipped/deduped attempts) |
| `MarketDataCache` | `market_data_cache` | OHLCV + indicators + fundamentals (configurable TTL: lite_analysis 4h, full_analysis 4h) |
| `PortfolioSnapshot` | `portfolio_snapshots` | End-of-cycle portfolio state |
| `OpportunityScoreSnapshot` | `opportunity_score_snapshots` | Per-cycle UOV components and final/ewma scores per ticker |
| `OpportunityQueue` | `opportunity_queue` | Active queued BUY opportunities awaiting execution |
| `PerformanceMetric` | `performance_metrics` | Daily/rolling Sharpe, Sortino, drawdown, win rates by strategy, alpha |
| `TradeOutcome` | `trade_outcomes` | Per-trade P&L linking BUY to SELL/REDUCE with conviction and moderator linkage |
| `StopLossAdjustment` | `stop_loss_adjustments` | Audit trail for stop-loss reassessments, trailing ratchets, and limit orders |

## Configuration (config/settings.yaml)

Key tuneable values:

- **Trading**: `mode: practice`, `cycle_frequency: intraday|standard`, `cycle_times_utc`, `max_positions: 15`, `cash_floor_pct: 10`
- **Risk**: `max_single_stock_pct: 15`, `max_sector_pct: 35`, `halt_drawdown_pct: 15`
- **Strategy weights**: momentum `0.35`, mean_reversion `0.30`, factor `0.35`
- **Models**: `claude-sonnet-4-5-20250929` (strategy), `gpt-4o` + `gemini-2.5-flash` (moderation)
- **Universe**: `max_candidates: 30`, cap tiers 70/20/10% (large/mid/small), `screening_cooldown_hours: 72`
- **Data cache TTLs** (configurable): `ohlcv_indicators: 4h`, `fundamentals: 12h`, `finnhub_analyst: 6h`, `alpha_vantage_broad: 4h`, `macro_intelligence: 4h`
- **Cost**: Anthropic £1/day, OpenAI £0.75/day, Google £0.50/day, monthly cap £50
- **Opportunity**: `enabled`, `mode: shadow|active`, immediate/queue z-thresholds, queue TTL, swap delta, EWMA half-life, weighted feature map, stage penalties
- **Order management**: `enabled`, `reassess_stops`, `trailing_stops` (enabled, trail_pct), `limit_orders` (enabled, offset_pct, validity), ATR multiplier, min/max stop distance, only_tighten_stops
- **Notifications**: `enabled`, channels/routes, retry/timeout/dedup config, dry-run alert policy, command gateway flag (disabled in v1)

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
| `docs/BACKTESTING.md` | What backtesting is, why it matters, how implemented, benefits |
| `docs/WALK_FORWARD_VALIDATION.md` | Walk-forward validation and promotion report |
| `docs/DATA_EXPORT_RUNBOOK.md` | VPS-to-local data export procedure, integrity checks |

**How to update:** After implementing a feature, scan each file above for sections that reference the changed area. Update inline — do not leave stale descriptions. Keep the same tone and depth as the existing content.

**Test count:** Update `README.md` status line (`N tests passing`) whenever tests are added or removed.

## Project Evolution Context

- **Current state:** POC v1.0 — deployed to VPS for live data collection on Trading 212 Practice
- **Development team:** Project Lead (PhD Maths, DS Manager), Claude Code Opus 4.6 (cloud, primary dev), Codex 5.3+ (local VS Code, secondary dev)
- **Principles:** Innovation, simplicity, elegance, transparency. No feature for technology's sake.
- **Key docs:** `docs/SOPHISTICATION_ROADMAP.md` (backlog), `docs/COMPETITIVE_ANALYSIS.md` (positioning)


## Near-term delivery focus (updated)

Current primary user stories for next-week implementation:
- **US-1.5 Chat Interface & Real-Time Trade Alerts** (`docs/CHAT_INTERFACE_PROJECT.md`) [delivered; outbound phase complete]
- **US-5.1 Backtesting Engine foundations** (`docs/BACKTESTING_PROJECT_PLAN.md`) [delivered; engine, walk-forward, promotion report, yfinance fetch + CSV cache]

Primary build focus in the next coding session is calibration (US-2.1, US-2.2) and portfolio optimisation (US-3.1).

When touching this track, keep `README.md`, `docs/ARCHITECTURE.md`, `docs/SOPHISTICATION_ROADMAP.md`, and `docs/BACKTESTING_PROJECT_PLAN.md` synchronized in the same PR.
