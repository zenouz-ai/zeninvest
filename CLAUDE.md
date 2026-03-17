# CLAUDE.md — AI Context for Investment Agent

This file provides context to AI assistants (Claude Code, Codex, Cursor, etc.) working on this repo.

## What This Project Is

Autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM pipeline. Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Journal.

**Scheduling architecture:** Configurable via `cycle_frequency` in `config/settings.yaml`:
- **intraday** (default): 3 cycles at 08:00, 12:00, 16:00 UTC — more timely decisions, uses deferred Finnhub/AV and tiered caching to stay within API limits.
- **standard**: 2 cycles at 07:00, 19:00 UTC — original 12-hour cadence.
Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Order Management (stop-loss reassessment, trailing stops, limit orders) → Journal.

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

# UOV diagnostic run (shadow mode + emit scores for calibration)
poetry run python -m src.orchestrator.main --uov-diagnostic

# Continuous scheduler
poetry run python -m src.scheduler.scheduler

# System controls
poetry run python -m src.orchestrator.main --status
poetry run python -m src.orchestrator.main --performance
poetry run python -m src.orchestrator.main --dashboard
poetry run python -m src.orchestrator.main --pause
poetry run python -m src.orchestrator.main --resume
poetry run python -m src.orchestrator.main --reset-peak   # Clear CAUTIOUS when peak was set incorrectly
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
poetry run python -m src.orchestrator.main --report
# Backtesting (real data: fetches yfinance if data/backtest/ empty, caches to CSV)
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1

# Diagnostics notebook (tests every pipeline component independently)
poetry run jupyter notebook notebooks/diagnostics.ipynb
```

## Project Layout

```
src/
├── orchestrator/          # Main cycle loop (main.py) + state machine (ACTIVE/CAUTIOUS/HALTED)
├── agents/
│   ├── market_data/       # DataFetcher, FinnhubClient, AlphaVantageClient, macro_intelligence, brave_enrichment, universe screener, seed_universe
│   ├── strategy/          # StrategyEngine (Claude synthesis), momentum, mean_reversion, factor
│   ├── moderation/        # ModerationPanel — GPT-4o (skeptic) + Gemini (risk assessor) consensus
│   ├── risk/              # RiskManager — 9 hard rules with VETO power, no LLM involvement
│   ├── opportunity/       # OpportunityScorer + OpportunityOptimizer — UOV ranking, queueing, swap suggestions
│   ├── research/          # Agentic research (US-4.4): providers (Brave, Tavily), SEC EDGAR, cache, budget, executor
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
    ├── search_api_tracker.py  # Brave/Tavily monthly call limits via api_logs
    └── logger.py          # Rich logging
dashboard/
└── backend/               # Dashboard API backend (Phase 1)
    └── app/
        ├── main.py        # FastAPI app with CORS, lifespan events
        ├── database.py    # Dashboard models (EventsLog, Run) + init
        ├── schemas.py     # Pydantic response models
        ├── routers/       # REST endpoints (runs, universe, portfolio, orders, events/SSE)
        └── services/
            └── event_logger.py  # Non-blocking event logger (agent can import)
config/
├── settings.yaml          # All tuneable parameters (trading, risk, strategy, universe, costs, notifications)
└── .env.example           # Environment variables template (required core API keys + optional notification keys)
notebooks/
├── diagnostics.ipynb      # 24-section Jupyter notebook testing every pipeline component (Config → Backtesting → Walk-Forward)
├── research_api_investigation.ipynb  # Phase 0: Brave/Tavily/SEC EDGAR API validation
├── research_api_decision_framework.ipynb  # Phase 0.2: Follow-up routing policy validation
├── enriched_instruments.ipynb  # Inspect enriched instrument data (sector, market_cap, industry, summary)
├── brave_api_smoke.py     # Manual smoke test for Brave Search + Answers APIs (requires API keys)
├── brave_tavily_comparison.py  # Compare Brave vs Tavily extraction (sector, market_cap)
└── enrichment_benchmark.py    # Benchmark BRAVE_SEARCH vs BRAVE_ANSWERS vs TAVILY: cost, time, accuracy
tests/                     # pytest — conftest sets INVESTMENT_AGENT_USE_INMEMORY_DB so all tests use in-memory SQLite; never touch production DB
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

`conftest.py` sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1` before any imports so `src.data.database` uses `sqlite:///:memory:` during pytest. Tests never write to `data/investment_agent.db`.

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

Trading 212 and yfinance use different ticker formats. **Always convert when crossing boundaries.** Use `ticker_utils.t212_to_yf()` (single source of truth; handles `_US_EQ`/`_UK_EQ`, class A `TAP/A`→`TAP-A`, class B `BRK_B`→`BRK.B`).

| Context | Format | Example |
|---------|--------|---------|
| T212 API / database (`Instrument.ticker`) | `SYMBOL_COUNTRY_EQ` | `AAPL_US_EQ`, `BP._UK_EQ` |
| yfinance / indicators / fundamentals | Clean symbol | `AAPL`, `BP.L` |

```python
from src.utils.ticker_utils import t212_to_yf
yf_ticker = t212_to_yf(ticker)
```

Execution guardrail: strategy output may occasionally return plain symbols (`AAPL`, `NEM`, etc.). The orchestrator normalizes these to T212 instrument IDs (`AAPL_US_EQ`, `NEM_US_EQ`) via `stocks_data` and an instruments-table fallback before order placement.

## Architecture Rules

1. **Risk rules are deterministic Python** — never call an LLM from `RiskManager`. Its VETO is final.
2. **Defense in depth** — every trade passes Strategy → Moderation → Risk → Execution. Any layer can block.
3. **State machine** — ACTIVE → CAUTIOUS (config `cautious_drawdown_pct`, default 30%) → HALTED (config `halt_drawdown_pct`, default 40%). HALTED requires manual recovery. Drawdown uses `totalValue` from T212 account summary (includes reserved/pending orders); fallback: cash + invested + reservedForOrders. **Practice account** (`trading.account_type: practice`): state machine is relaxed — always stays ACTIVE; drawdown is logged but never triggers CAUTIOUS/HALTED. Use `account_type: live` for real money to enable full state machine.
4. **Screening cooldown & mix** — Universe screening runs every cycle regardless of state (including CAUTIOUS); Risk blocks new BUYs in CAUTIOUS. `Instrument.last_screened_at` is stamped after each screen. Cooldown: `effective_screening_cooldown_hours` = `effective_screening_cooldown_override` if set (e.g. 12h); else for intraday `min(screening_cooldown_hours, cycle_hours)` (e.g. 4h); for standard uses `screening_cooldown_hours` (12h). The screener uses time-based buckets: **review** = investigated 24–48h ago (last StrategyDecision in `review_window_hours`); **new** = never investigated or last >48h ago. Targets 50% from each pool via `uninvestigated_target_pct` (new share). When the pool is exhausted (all instruments in cooldown), the fallback orders by `last_screened_at ASC` (least recently screened first) to rotate. **Proactive seed**: when eligible pool &lt; 2×max_candidates, seed instruments are merged to ensure rotation headroom.
5. **Curated seed universe & enrichment cascade** — `seed_universe.py` is derived from T212's instrument list (~6900 US equities, 100% tradeable). Regenerate with `poetry run python scripts/generate_seed_from_t212.py --from-db`. **Bulk enrichment:** one-off `poetry run python scripts/bulk_enrich_instruments.py` (parallel yfinance) to populate sector, market_cap, industry, business_summary, exchange, currency, name. **Backfill:** `poetry run python scripts/backfill_industry_summary.py` for instruments that already have sector+market_cap but lack industry/summary/name. Used as fallback when instruments table lacks enriched data; only enriches instruments present in DB (T212-available). Scheduled batch enrichment (`enrich_instruments_batch`) cascades: yfinance → Finnhub → Alpha Vantage OVERVIEW → BRAVE_ANSWERS; saves industry and business_summary when available. Tickers that fail yfinance OHLCV fetch are flagged `data_available=False` and permanently excluded.
5a. **Deferred Finnhub/AV (intraday)** — When `cycle_frequency: intraday`, screening uses `get_stock_analysis_lite` (yfinance only). Finnhub and Alpha Vantage are fetched only for `positions ∪ top_tickers` (active-review tickers), with `NewsSentimentCache` lookup first.
5b. **Web search fallback** — When Finnhub analyst data or Alpha Vantage ticker sentiment times out or fails, `get_news_sentiment_fallback` (Brave/Tavily) supplies analyst/news-like snippets for the strategy prompt. Controlled by `data_fallback_web_search_enabled`; respects search API monthly budget.
5c. **Queued ticker re-evaluation** — When opportunity is enabled, Phase 3 in `_fetch_stocks_data` re-adds queued tickers (from OpportunityQueue) to stocks_data each cycle, bypassing screening cooldown, so they can reach 2nd cycle and promote before expiring.
6. **Company profiles** — `longBusinessSummary` + `industry` from yfinance are persisted in the `Instrument` model and included in the Claude strategy prompt for qualitative reasoning. When yfinance returns sparse data, the orchestrator falls back to Instrument.industry and Instrument.business_summary (enriched by bulk/backfill scripts; ~5,477 instruments deployed).
7. **T212 order status** — Order status is derived from T212 API response `status`: FILLED/PARTIALLY_FILLED→filled, NEW/CONFIRMED/UNCONFIRMED/LOCAL→pending, REJECTED/CANCELLED→failed. Do not assume filled on 200 OK. **Order sync**: At the start of each cycle (non–dry-run), `OrderManager.sync_order_status_from_t212()` fetches T212 order history and updates local `Order.status` from pending to filled when T212 reports FILLED.
8. **Cost degradation** — FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED. When only one moderator is over budget (Google or OpenAI), returns NO_GEMINI (one moderator still operational); when both are over budget, returns NO_GPT4O (no moderation). Individual moderators self-check their own budgets before each call. Budget per-provider per-day, plus monthly cap. **Research costs** tracked separately in `research_logs.cost_usd` ($0.005/paid call); surfaced in dashboard Costs page as a distinct "Agentic Research" band (daily chart + monthly table) alongside LLM and API costs. `/api/research/summary` returns cost breakdowns by member, tool, and provider.
9. **Order dedup** — 5-minute window prevents double-execution of the same order.
10. **Order value floor** — `min_order_value_gbp` applies to BUY/REDUCE/limit/stop paths; explicit market SELL decisions may execute below the floor so small positions can be fully exited. REDUCE that would leave a sub-£500 residual is auto-converted to full SELL.
11. **Stop-loss** — automatically placed after every BUY using Claude's `stop_loss_pct` (GTC validity).
12. **UOV optimizer guardrail** — UOV may reorder/queue BUYs, but it never directly triggers SELL/REDUCE. Strategy remains sell authority; Risk remains final veto.
12. **Notification fail-open** — alert delivery failures (Slack/Email) must never block trade execution.
13. **Intelligent order management** — `StopLossManager` runs after execution each cycle. Stop-loss is placed for BUY when `exec_result.status` in (filled, dry_run, **pending**) — optimistic placement for market BUYs that may fill shortly. **Place missing stops**: `place_missing_stops()` runs before reassessment; positions without a pending stop get one using `default_stop_loss_pct` (or ATR-based when available). Three capabilities:
    - **ATR-based stop reassessment**: Recalculates stops using 14-day ATR × configurable multiplier, clamped to [min, max] distance. By default only tightens (never widens).
    - **Software trailing stops**: Tracks high-water mark per position. Ratchets stop up as price rises. Implemented by cancel + replace since T212 has no native trailing stop.
    - **Limit dip-buy orders**: When strategy outputs `entry_type: "limit_dip"`, places limit BUY below current price instead of market order. Offset % configurable globally or per-decision.
    - All adjustments logged to `stop_loss_adjustments` table and emitted as `order_adjustment` Slack notifications.
13. **Agentic research (US-4.4)** — When `research.enabled`, Strategy/Skeptic/Risk can use tools: `web_search`, `news_search`, `sector_search`, `sec_search` (SEC EDGAR), `macro_search` (macro-economic). Per-member caps 20/8/7, total 35/cycle. Brave primary, Tavily fallback. SEC EDGAR free. Pipeline shares a single `ResearchExecutor`/`ResearchBudget` across Strategy and Moderation for pipeline-wide cap enforcement. All three members (Strategy, GPT-4o Skeptic, Gemini Risk) have full tool-use loops. Latency and cost recorded per call. 37 unit tests. See `docs/AGENTIC_RESEARCH.md`.
14. **Dashboard backend (Phase 1 + Phase 1.5 + full API)** — FastAPI REST API + SSE stream. Endpoints: runs, status (includes system state and paused), universe, portfolio, orders, events/stream; decisions (with pipeline waterfall), moderation, risk; opportunity (scores, queue, history); outcomes (list, stats); stop-loss (current, adjustments); performance (metrics, history); costs (daily, monthly, degradation); api-usage (daily); system (state, trigger-cycle, pause, resume); POST /api/runs/trigger (dry-run), POST /api/runs/trigger-live (live cycle). All query agent SQLite read-only; no duplicate tables. Event logger: non-blocking, fail-open. Frontend: 8 pages — Dashboard Home (state badge, Dry Run and Live Run buttons; Live Run requires confirmation), Universe (sortable columns, expandable rows with full LLM outputs: strategy reasoning + extra fields + raw JSON, all moderators’ verdicts/reasoning, risk reasoning and rules), Run History, Portfolio, Opportunity Pipeline, Order Management (Recent Orders + stop-loss levels + adjustments), Costs, Roadmap & Architecture (project timeline, architecture diagram). When CAUTIOUS, "Reset Peak" button clears false drawdown. Order status reflects T212 response (filled/pending/failed). Universe table includes `Investigated`, `Reviews`, `Decisions`, `Holding`, `Sold`, and `UOV (ewma)` columns; `Sold` is the total number of shares sold based on executed and dry-run SELL orders only (orders store SELL quantities as negative, but the dashboard reports `abs(sum(quantity))`). For transparency, the backend also exposes a live vs dry-run breakdown per ticker so the UI can show cases where Sold > 0 comes entirely from hypothetical dry-run cycles with no live Trading 212 execution. Cycle summary includes rejected_by_action (breakdown by strategy action: BUY, HOLD, QUEUED). For HOLD/QUEUED, moderation_consensus and risk_verdict are "not invoked"; rejection stages: strategy_hold, strategy_queued. Design: dark charcoal #0d1117, gain #00ff88, loss #ff4444, neutral #58a6ff, accent #d4a017, subtle grid background. Research API: `GET /api/research/logs`, `GET /api/research/ticker/{ticker}`, `GET /api/research/summary`. Universe table includes a `Research` column showing per-ticker research call count; expandable rows include an **Agentic Research** block showing which pipeline member (Strategy/Skeptic/Risk) used which tool, the query, results summary, cache hit, provider, latency, and cost — enabling full transparency into how research influenced each decision. Config: `dashboard.enabled`, `dashboard.events_enabled`.

## Scheduling Architecture

The scheduler (`src/scheduler/scheduler.py`) creates one cron job per entry in `settings.cycle_times_utc`. Cycle times are resolved from `cycle_frequency`:

| `cycle_frequency` | `cycle_times_utc` | `cycle_hours` | Use case |
|------------------|------------------|---------------|----------|
| `intraday` | 08:00, 12:00, 16:00 UTC | 4 | 3 runs during market hours; deferred Finnhub/AV + tiered cache |
| `standard` | 07:00, 19:00 UTC | 12 | Original 2-cycle cadence |

Other scheduled jobs (unchanged): daily snapshot 21:30 UTC, weekly report Fri 22:00 UTC, instrument refresh Sun 12:00 UTC.

**Run deduplication:** Scheduled cycles produce a single Run record. The scheduler creates a Run with `cycle_id = scheduled_YYYYMMDD_HHMMSS`, passes it to `orchestrator.run_cycle(scheduled_cycle_id=...)`, and the orchestrator uses that cycle_id and updates the Run on completion (it does not create a second Run).

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

Optional research keys (for Agentic Research, US-4.4):

```
TAVILY_API_KEY=...   # Tavily Search; required if Tavily is primary, fallback, or additional provider
```

Optional enrichment keys (for batch universe enrichment via Brave/Tavily + Gemini):

```
BRAVE_SEARCH_API_KEY=...  # Brave Web Search; sector/market_cap extraction
BRAVE_ANSWER_API_KEY=...  # Brave AI Answers; sector/market_cap extraction
TAVILY_API_KEY=...        # Tavily (also used for enrichment when Brave unavailable)
```

Search API budget: 2,000 calls/month each (config: `search_api_limits`). Logged to `api_logs`; enforced by `search_api_tracker`.

**Web API pricing (as of 2026-03):**
- **Brave Search:** $5.00 per 1,000 requests; 50 RPS; free $5 credits/month.
- **Brave Answers:** $4.00 per 1,000 queries + $5/1M input tokens + $5/1M output tokens; 2 RPS; free $5 credits/month.
- **Tavily:** Free Researcher = 1,000 credits/month; pay-as-you-go = $0.008/credit; Project plan = $30/month for 4,000 credits. 2,000 calls ≈ $16 pay-as-you-go or covered by Project plan.

Research tools use a provider abstraction: Brave (primary) + Tavily (fallback, optionally additional). See `docs/AGENTIC_RESEARCH.md`.

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
- **formatters.py** — Channel-specific rendering (`render_event` → Slack/Email). Trade/queued messages include ticker, action, quantity (or "queued"), committee summary (Moderation=X | Risk=Y, or "—" when committee not invoked e.g. HOLD), reasoning excerpt, and structured stage reason for queued/filtered decisions (e.g. "Awaiting 2nd cycle for promotion", "Capacity gated (no slot or cash)", "Below UOV queue threshold").
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
| `ApiLog` | `api_logs` | External API call audit trail (T212, Finnhub, Alpha Vantage, brave_search, brave_answers, tavily) |
| `ResearchLog` | `research_logs` | Agentic research tool calls (member, ticker, tool, provider, cache_hit) — US-4.4 |
| `NotificationLog` | `notification_logs` | Outbound alert audit trail (sent/failed/skipped/deduped attempts) |
| `MarketDataCache` | `market_data_cache` | OHLCV + indicators + fundamentals (configurable TTL: lite_analysis 4h, full_analysis 4h) |
| `PortfolioSnapshot` | `portfolio_snapshots` | End-of-cycle portfolio state. `positions_json` stores normalised positions (ticker, quantity, value_gbp, pnl_gbp, pnl_pct) converted from T212 `instrument.ticker` and `walletImpact` |
| `OpportunityScoreSnapshot` | `opportunity_score_snapshots` | Per-cycle UOV components and final/ewma scores per ticker |
| `OpportunityQueue` | `opportunity_queue` | Active queued BUY opportunities awaiting execution |
| `PerformanceMetric` | `performance_metrics` | Daily/rolling Sharpe, Sortino, drawdown, win rates by strategy, alpha |
| `TradeOutcome` | `trade_outcomes` | Per-trade P&L linking BUY to SELL/REDUCE with conviction and moderator linkage |
| `StopLossAdjustment` | `stop_loss_adjustments` | Audit trail for stop-loss reassessments, trailing ratchets, and limit orders |
| `EventsLog` | `events_log` | Real-time activity stream for dashboard SSE (event_type, source, message, metadata_json) |
| `Run` | `runs` | Run metadata (cycle_id, run_type, started_at, completed_at, status, summary_json) |

## Configuration (config/settings.yaml)

Key tuneable values:

- **Trading**: `mode`, `account_type: practice|live` (practice = relaxed state machine), `cycle_frequency: intraday|standard`, `cycle_times_utc`, `max_positions: 15`, `cash_floor_pct: 10`, `min_order_value_gbp: 500` (BUY/REDUCE/limit/stop floor; explicit market SELL exempt), `min_reduce_pct_of_position: 25`, `reduce_tiers_pct: [25, 50, 70, 100]`
- **Risk**: `min_holding_hours_before_reduce: 24`, `max_single_stock_pct: 15`, `max_sector_pct: 35`, `cautious_drawdown_pct: 30`, `halt_drawdown_pct: 40`
- **Strategy weights**: momentum `0.35`, mean_reversion `0.30`, factor `0.35`
- **Models**: `claude-sonnet-4-5-20250929` (strategy), `gpt-4o` + `gemini-2.5-flash` (moderation)
- **Universe**: `max_candidates: 35`, cap tiers 70/20/10% (large/mid/small), `screening_cooldown_hours: 12`, `effective_screening_cooldown_override: 12`, `review_window_hours: [24, 48]`, `data_fallback_web_search_enabled`, `batch_enrichment_enabled`, `batch_enrichment_per_run`
- **Strategy**: One decision per ticker (up to 35). Actions: BUY, SELL, HOLD, REDUCE, QUEUED. Targets 60+ decisions/day (3 cycles × 20+ through full pipeline).
- **Data cache TTLs** (configurable): `ohlcv_indicators: 4h`, `fundamentals: 12h`, `finnhub_analyst: 6h`, `alpha_vantage_broad: 4h`, `macro_intelligence: 4h`
- **Cost**: Anthropic £1/day, OpenAI £0.75/day, Google £0.50/day, monthly cap £50; **search_api_limits**: 2,000 brave_search, 2,000 brave_answer, 1,000 tavily
- **Research** (US-4.4): `enabled`, `strategy_research_enabled`, `skeptic_research_enabled`, `risk_research_enabled`; caps 20/8/7 per member, 35 total/cycle
- **Opportunity**: `enabled`, `mode: shadow|active`, `immediate_threshold_z` (0.3), `queue_threshold_z` (0.0), `queue_ttl_cycles` (6), swap delta, EWMA half-life, weighted feature map, stage penalties. Rejection reasons are structured (`awaiting_promotion`, `capacity_gated`, `below_immediate`, `below_queue`, `queue_expired`, `no_longer_eligible`). Queued tickers re-evaluated each cycle (Phase 3 in _fetch_stocks_data) bypassing cooldown.
- **Order management**: `enabled`, `default_stop_loss_pct: -8`, `reassess_stops`, `trailing_stops` (enabled, trail_pct), `limit_orders` (enabled, offset_pct, validity), ATR multiplier, min/max stop distance, only_tighten_stops
- **Notifications**: `enabled`, channels/routes, retry/timeout/dedup config, dry-run alert policy, command gateway flag (disabled in v1)
- **Dashboard**: `enabled`, `events_enabled`, `cors_origins` (list of allowed CORS origins; defaults to localhost when absent) (Phase 1 backend: REST API + SSE stream)

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
| `docs/LOCAL_SETUP.md` | New setup steps, new pre-flight checks, new CLI commands |
| `docs/DEPLOYMENT.md` | Infrastructure changes, new env vars, new Docker config, new systemd settings |
| `docs/DATA_RATIONALE.md` | New data sources, removed data points, changed data flow |
| `docs/SOPHISTICATION_ROADMAP.md` | Features completed (move to "done"), new user stories added |
| `docs/COMPETITIVE_ANALYSIS.md` | Positioning changes, new differentiators, market landscape updates |
| `docs/CHAT_AND_COMMANDS.md` | Chat alerts, command interface scope, Slack trade commands |
| `docs/ORDER_MANAGEMENT_PROJECT.md` | Stop-loss and limit order management: current design, config, future sophistication |
| `docs/BACKTESTING.md` | Backtesting scope, engine design, validation assumptions, walk-forward validation, promotion report |
| `docs/DATA_EXPORT_RUNBOOK.md` | VPS-to-local data export procedure, integrity checks |
| `docs/DASHBOARD.md` | Dashboard architecture, phases, data alignment, frontend/backend design |
| `docs/DASHBOARD_DEPLOYMENT.md` | Dashboard VPS deployment: Docker service, VPS IP access, firewall |
| `docs/AGENTIC_RESEARCH.md` | Agentic research: independent tool access, implementation plan, phase breakdown |

**How to update:** After implementing a feature, scan each file above for sections that reference the changed area. Update inline — do not leave stale descriptions. Keep the same tone and depth as the existing content.

**Test count:** Update `README.md` status line (`N tests passing`) whenever tests are added or removed.

## Project Evolution Context

- **Current state:** POC v1.0 — deployed to VPS for live data collection on Trading 212 Practice
- **Development team:** Project Lead (PhD Maths, DS Manager), Claude Code Opus 4.6 (cloud, primary dev), Codex 5.3+ (local VS Code, secondary dev)
- **Principles:** Innovation, simplicity, elegance, transparency. No feature for technology's sake.
- **Key docs:** `docs/SOPHISTICATION_ROADMAP.md` (backlog), `docs/COMPETITIVE_ANALYSIS.md` (positioning)


## Near-term delivery focus (updated 2026-03-13)

**Delivered:**
- **US-1.5** Chat Interface & Real-Time Trade Alerts
- **US-5.1** Backtesting Engine (engine, walk-forward, promotion report)
- **US-1.8** Dashboard VPS Deployment
- **US-1.7** Dashboard full spec (full API + 8 pages)
- **US-1.4** Deploy POC to VPS
- **US-4.4** Agentic Research — 5 tools, all 3 members have tool-use loops, shared pipeline-wide budget, 37 tests

**Deferred (await data or later sprint):**
- Calibration (US-2.1, US-2.2) — requires ~50 trades
- US-5.2 Parameter sensitivity harness
- US-1.6 Slack NL trade commands

## Known issues (2026-03-13)

1. **Dashboard VPS deployment** — US-1.8 delivered; deployment checklist in `docs/DASHBOARD_DEPLOYMENT.md`. Operator runs: pull, `ufw allow 8000/tcp`, `docker compose up -d --build` → dashboard running at `http://VPS_IP:8000`. Phase 1.5 Analytics Lite delivered (Decision Explorer, run diff, next-run countdown, P&L). Activity feed SSE uses relative URL.
2. **Dry-run state mutation** — Fixed (commit `e5e6f46`). Dry-run no longer mutates drawdown state or skips screening.
3. **Duplicate Run per scheduled cycle** — Fixed. Scheduler now passes `scheduled_cycle_id` to orchestrator; one Run per cycle (scheduler creates, orchestrator updates).
4. **Finnhub timeouts in cloud VMs** — Finnhub API calls may time out in VPS/cloud environments due to network latency. Pipeline handles gracefully: analyst recommendations and insider sentiment are missing but cycle completes. See AGENTS.md.

When touching the dashboard track, keep `README.md`, `docs/ARCHITECTURE.md`, `docs/SOPHISTICATION_ROADMAP.md`, `docs/DASHBOARD.md`, and `docs/DASHBOARD_DEPLOYMENT.md` synchronized.
