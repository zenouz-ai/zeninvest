# CLAUDE.md — AI Context for ZenInvest

This file is the lean working context for AI assistants in this repo. Detailed scheduling, deployment, and setup instructions live in the docs linked below.

## What This Project Is

ZenInvest is an autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM committee:

```text
Data -> Universe Screen -> Strategy (Claude) -> Moderation (GPT-4o + Gemini) -> Risk (hard rules, VETO) -> Opportunity (UOV) -> Execution (T212) -> Order Management -> Journal
```

Macro intelligence runs on its own schedule, derives `RISK_ON` / `RISK_OFF` / `NEUTRAL`, and injects that regime into strategy and moderation context. Agentic research allows Strategy, Skeptic, and Risk to use live web, news, sector, SEC, and macro tools under strict per-cycle budgets.

Use these docs for the full picture:

- `docs/ARCHITECTURE.md` — pipeline, scheduling, macro intelligence, dashboard topology
- `docs/LOCAL_SETUP.md` + `config/.env.example` — env vars, install, local runtime
- `docs/DEPLOYMENT.md` — Docker/VPS/notification operations
- `docs/SOPHISTICATION_ROADMAP.md` + `dashboard/frontend/src/data/roadmap.ts` — delivery status
- `AGENTS.md` — operational caveats for this environment

## Quick Commands

```bash
poetry install
poetry run alembic upgrade head
poetry run pytest -v
poetry run mypy src/

poetry run python -m src.orchestrator.main --dry-run
poetry run python -m src.orchestrator.main
poetry run python -m src.orchestrator.main --uov-diagnostic

poetry run python -m src.scheduler.scheduler

poetry run python -m src.orchestrator.main --status
poetry run python -m src.orchestrator.main --performance
poetry run python -m src.orchestrator.main --dashboard
poetry run python -m src.orchestrator.main --pause
poetry run python -m src.orchestrator.main --resume
poetry run python -m src.orchestrator.main --reset-peak
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
poetry run python -m src.orchestrator.main --report

poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
```

## Project Layout

```text
src/
├── orchestrator/   # run_cycle(), state machine, controls
├── agents/
│   ├── attribution/    # strategy change episodes and evidence
│   ├── conversation/   # chat orchestration, proposals, confirmations, research trace
│   ├── evolution/      # Evolution Planner workflow tables and services
│   ├── guidance/       # market guidance overlays and regime-aware sector tilt
│   ├── market_data/    # yfinance/Finnhub/AV fetchers, screening, macro intelligence
│   ├── strategy/       # momentum, mean reversion, factor, Claude synthesis
│   ├── moderation/     # GPT-4o skeptic + Gemini risk assessor
│   ├── risk/           # deterministic rules, never LLM-driven
│   ├── opportunity/    # UOV scoring and queueing
│   ├── research/       # Brave/Tavily/SEC EDGAR research tooling and budgets
│   ├── execution/      # T212 client, order manager, stop management
│   ├── notifications/  # Slack/email delivery and chat command handling
│   └── reporting/      # journals, reports, performance, trade outcomes
├── data/           # SQLite, SQLAlchemy models, Alembic migrations
├── scheduler/      # APScheduler jobs
├── backtesting/    # engine, broker, metrics, walk-forward
└── utils/          # config, logging, budgets, helpers

dashboard/
├── backend/        # FastAPI API + SSE + auth + public/private route split
└── frontend/       # React/Vite 12-page dashboard surface

config/             # settings.yaml + .env.example
docs/               # architecture, deployment, governance, roadmap, feature docs
tests/              # pytest; in-memory SQLite via conftest.py
```

## Key Patterns

### Imports — always absolute

```python
from src.agents.strategy.engine import StrategyEngine
from src.utils.config import get_settings
from src.data.database import get_session
from src.data.models import Instrument, Order
```

Never use relative imports.

### Settings — singleton

```python
settings = get_settings()
settings.max_single_stock_pct
settings.screening_cooldown_hours
settings.t212_api_key
```

Add new YAML-backed keys to `src/utils/config.py`.

### Database sessions

```python
session = get_session()
try:
    ...
    session.commit()
except Exception:
    session.rollback()
    raise
finally:
    session.close()
```

### Test fixtures — in-memory SQLite

`tests/conftest.py` sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1` before imports so pytest never touches `data/investment_agent.db`.

```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

## Ticker Format Gotcha

Trading 212 and yfinance use different formats. Always convert when crossing boundaries with `ticker_utils.t212_to_yf()`.

| Context | Format | Example |
|---------|--------|---------|
| T212 / database | `SYMBOL_COUNTRY_EQ` | `AAPL_US_EQ`, `BP._UK_EQ` |
| yfinance / indicators | native symbol | `AAPL`, `BP.L` |

```python
from src.utils.ticker_utils import t212_to_yf

yf_ticker = t212_to_yf(ticker)
```

The orchestrator also normalizes plain strategy outputs like `AAPL` back to T212 instrument IDs before execution.

## Architecture Rules

1. **Risk stays deterministic.** `RiskManager` never calls LLMs for autonomous trading decisions.
2. **Defense in depth is mandatory.** Scheduled and strategy-triggered trades flow through Strategy -> Moderation -> Risk -> Execution.
3. **State machine matters.** `ACTIVE -> CAUTIOUS -> HALTED`; Practice mode logs drawdown but does not enforce the live-account state machine.
4. **Screening always runs.** CAUTIOUS blocks new BUYs via risk, not by skipping screening.
5. **Universe eligibility is rate-limited.** Cooldowns, review limits, and proactive seeding prevent thrashing and concentration in the same names.
6. **Use the enrichment cascade.** Prefer stored enriched instrument metadata; enrichment flows yfinance -> Finnhub -> Alpha Vantage -> Brave Answers.
7. **Intraday mode is lite first.** Screening uses cheaper/faster data first, then fetches heavier Finnhub/Alpha Vantage context only for positions and active-review names.
8. **Web-search fallback is budgeted.** Brave/Tavily only step in when configured and when native sentiment/analyst data is missing.
9. **Order truth comes from Trading 212.** Persist before submit, reconcile against broker state, and never treat HTTP 200 as equivalent to filled.
10. **Mutating broker calls are not retried.** Only safe reads are retried automatically.
11. **Cost degradation must be graceful.** `FULL -> NO_GEMINI -> NO_GPT4O -> NO_STRATEGY -> HALTED`; moderators also self-check provider budgets.
12. **Order management is protective, not optional.** Missing stops, profit-lock thresholds, stale pending-order cleanup, and stop reassessment are first-class flows.
13. **Agentic research is shared-budget.** Strategy, Skeptic, and Risk all have tool loops, but the pipeline enforces one shared research budget and audit log.
14. **Conversation and evolution are policy-gated.** Chat proposals are confirm/reject versioned, and evolution planning is intentionally separated from code/deploy authority.
15. **Dashboard and chat are operators, not shadow systems.** They read the same SQLite truth, expose audited actions, and keep sensitive routes behind operator auth.

### Macro Intelligence Summary

`src/agents/market_data/macro_intelligence.py` aggregates sector performance, macro headlines, and regime state, then persists that posture for both the strategy pipeline and the World News dashboard. The authoritative design details live in `docs/ARCHITECTURE.md`.

## Database Models (`src/data/models.py`)

| Model | Table | Purpose |
|-------|-------|---------|
| `SystemState` | `system_state` | Trading state, pause flag |
| `Instrument` | `instruments` | T212 universe plus enriched metadata |
| `Order` | `orders` | Submitted, filled, failed, dry-run, pending, cancelled orders |
| `StrategyDecision` | `strategy_decisions` | Strategy proposals and reasoning |
| `ModerationLog` | `moderation_logs` | GPT-4o and Gemini verdicts |
| `RiskDecision` | `risk_decisions` | Triggered rules and veto results |
| `CostLog` | `cost_logs` | Per-provider LLM cost tracking |
| `ApiLog` | `api_logs` | External API audit trail |
| `ResearchLog` | `research_logs` | Agentic research usage by member/tool/provider |
| `NotificationLog` | `notification_logs` | Outbound alert delivery history |
| `MarketDataCache` | `market_data_cache` | Cached OHLCV, indicators, fundamentals |
| `PortfolioSnapshot` | `portfolio_snapshots` | End-of-cycle holdings and valuation state |
| `OpportunityScoreSnapshot` | `opportunity_score_snapshots` | UOV components and final scores |
| `OpportunityQueue` | `opportunity_queue` | Queued BUY opportunities |
| `PerformanceMetric` | `performance_metrics` | Sharpe, Sortino, drawdown, win rate |
| `TradeOutcome` | `trade_outcomes` | BUY-to-SELL outcome tracking |
| `StopLossAdjustment` | `stop_loss_adjustments` | Stop/trailing/tiered adjustment audit trail |
| `MacroState` | `macro_state` | Regime, confidence, action plan, sector context |
| `MacroSignalLog` | `macro_signal_logs` | Normalized macro signals per scan |
| `MacroHeadline` | `macro_headlines` | Archived macro headlines |
| `EventsLog` | `events_log` | Dashboard SSE activity feed |
| `Run` | `runs` | Cycle and refresh metadata |

## Configuration (`config/settings.yaml`)

Keep this section high-signal. Detailed env var docs belong in `docs/LOCAL_SETUP.md`.

- **Trading:** `mode`, `account_type`, `cycle_frequency`, `schedule_mode`, `schedule_timezone`, `cycle_times_local`, `max_positions` (`20`), `cash_floor_pct` (`10`), `min_order_value_gbp` (`500`)
- **Risk:** `max_single_stock_pct` (`20`), `max_sector_pct` (`40`), drawdown thresholds (`30/40`), volatility gates (`25/35`), minimum holding windows
- **Strategy:** model IDs, weights, signal toggles, decision caps
- **Universe:** candidate counts, cooldowns, review limits, enrichment toggles
- **Cost:** provider daily budgets (`2/1/1 GBP`), monthly cap (`60 GBP`), search API limits (`2000/2000/1000`)
- **Research:** `enabled`, per-member caps (`20/8/7`), total cap (`35`)
- **Opportunity:** UOV mode, thresholds, queue TTL, EWMA tuning
- **Order management:** stop-loss defaults, trailing, tiered profit locks, limit-dip behavior
- **Notifications:** routes, retries, dedup, dry-run alert policy, command gateway, Slack trade commands
- **Dashboard:** enablement, SSE, CORS, auth/session settings
- **Conversation:** planner/transparency flags, per-turn specialist and research caps, separate chat LLM budget (`0.50 GBP/day`)

## When Adding New Features

- Add Alembic migrations for schema changes.
- Add new YAML-backed settings to `src/utils/config.py`.
- Wire new pipeline phases through `src/orchestrator/main.py` using the existing phase pattern.
- Add tests with in-memory SQLite fixtures and mock heavy external dependencies.
- Give new capabilities a kill switch and a documented fallback path.
- Update the canonical roadmap sources when delivery status changes.

### Documentation maintenance

Update docs in the same PR as the code change.

| File | Update when... |
|------|----------------|
| `README.md` | User-facing behavior, key commands, major features, test-count changes |
| `CLAUDE.md` | New architecture rules, settings, models, or repo patterns |
| `docs/ARCHITECTURE.md` | Pipeline, scheduling, data flow, dashboard/API topology |
| `docs/GOVERNANCE.md` | Risk rules, audit trail, safety posture |
| `docs/LOCAL_SETUP.md` | Setup, env vars, local run/test steps |
| `docs/DEPLOYMENT.md` | Infra, Docker, nginx, notifications, VPS posture |
| `docs/DASHBOARD.md` | Dashboard pages, UX, auth/public split, API shape |
| `docs/AGENTIC_RESEARCH.md` | Tooling, budgets, provider routing, audit model |
| `docs/SOPHISTICATION_ROADMAP.md` | Story status, delivery order, backlog changes |
| `dashboard/frontend/src/data/roadmap.ts` | Machine-readable milestone status for the dashboard |

## Project Status

ZenInvest is still a POC on Trading 212 Practice. The canonical delivery status is in `docs/SOPHISTICATION_ROADMAP.md` and `dashboard/frontend/src/data/roadmap.ts`; do not maintain sprint state or roadmap snapshots in this file.
