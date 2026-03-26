# CLAUDE.md — AI Context for Investment Agent

This file provides context to AI assistants (Claude Code, Codex, Cursor, etc.) working on this repo.

## What This Project Is

Autonomous investment agent that trades via the Trading 212 Practice API using a multi-LLM pipeline. Pipeline: Data → Universe Screen → Strategy (Claude) → Moderation (GPT-4o + Gemini) → Risk (hard rules, VETO) → Opportunity (UOV rank/queue) → Execution (T212) → Journal.

**Scheduling architecture:** Configurable via `cycle_frequency` in `config/settings.yaml`:
- **intraday** (default): 3 DST-aware market-session cycles at 10:00, 12:30, and 15:15 in `America/New_York` — more timely decisions, uses deferred Finnhub/AV and tiered caching to stay within API limits.
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
├── scheduler/             # APScheduler: analysis cycles from market-session local times or fixed UTC fallback, daily snapshot, weekly report, instrument refresh
├── backtesting/           # Engine, paper broker, io (load/fetch yfinance + CSV cache), metrics, walk-forward, promotion report
└── utils/
    ├── config.py          # Settings singleton via get_settings()
    ├── cost_tracker.py    # Per-provider budget enforcement + graceful degradation
    ├── search_api_tracker.py  # Brave/Tavily monthly call limits via api_logs
    └── logger.py          # Rich logging
dashboard/
├── backend/               # Dashboard API backend (Phase 1)
│   └── app/
│       ├── main.py        # FastAPI app with CORS, lifespan events
│       ├── database.py    # Dashboard models (EventsLog, Run) + init
│       ├── schemas.py     # Pydantic response models
│       ├── routers/       # REST endpoints (runs, universe, portfolio, orders, events/SSE)
│       └── services/
│           └── event_logger.py  # Non-blocking event logger (agent can import)
└── frontend/              # React + Vite + Tailwind frontend
    └── src/
        ├── pages/         # 11 pages: Dashboard, Universe, Portfolio, Opportunity, OrderManagement, RunHistory, Commands, WorldNews, Costs, Roadmap, Evolution
        ├── components/    # AlertBanner, LLMOutputBlocks, PageBrandHeader, Skeleton, Sparkline, PipelineWaterfall, PnlDisplay, FreshnessIndicator, LoadingSpinner, EmptyState, UniverseBubbleChart, Panel (glass-dark surface), MetricCard (Syne KPI), StatusPill (brand pill/badge), SectionHeader (Syne heading + mono eyebrow)
        ├── hooks/         # useSSE (real-time events), useAsyncData (independent section loading), useFocusTrap (modal keyboard trap)
        ├── api/client.ts  # Typed Axios API client (all endpoints)
        └── types/index.ts # TypeScript interfaces
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

1. **Risk rules are deterministic Python** — never call an LLM from `RiskManager`. Its VETO is final for autonomous cycles. For Slack trade commands, an explicit human `force` prefix can override the risk VETO (logged as `OVERRIDDEN`) on strategy-triggered trades. Plain direct BUY/SELL commands intentionally bypass strategy/moderation/risk and rely on broker-side preflight, confirmation, and execution safeguards instead.
2. **Defense in depth** — scheduled trades and strategy-triggered Slack trades pass Strategy → Moderation → Risk → Execution. Any layer can block. Moderation consensus has three tiers: APPROVED (full allocation), CAUTION (25% allocation reduction for BUY), BLOCKED (rejected). Moderator MODIFY verdicts count as conditional AGREE and their `modifications.target_allocation_pct` is applied as an allocation cap. Moderator `modifications` payloads are normalized defensively; malformed extras are ignored and must never crash scheduled or Slack single-ticker runs.
3. **State machine** — ACTIVE → CAUTIOUS (config `cautious_drawdown_pct`, default 30%) → HALTED (config `halt_drawdown_pct`, default 40%). HALTED requires manual recovery. Drawdown uses `totalValue` from T212 account summary (includes reserved/pending orders); fallback: cash + invested + reservedForOrders. **Practice account** (`trading.account_type: practice`): state machine is relaxed — always stays ACTIVE; drawdown is logged but never triggers CAUTIOUS/HALTED. Use `account_type: live` for real money to enable full state machine.
4. **Screening cooldown & mix** — Universe screening runs every cycle regardless of state (including CAUTIOUS); Risk blocks new BUYs in CAUTIOUS. `Instrument.last_screened_at` is stamped after each screen. Cooldown: `effective_screening_cooldown_hours` = `effective_screening_cooldown_override` if set (default active-swing `4h`); else for intraday `min(screening_cooldown_hours, cycle_hours)`; for standard uses `screening_cooldown_hours` (12h). Autonomous re-reviews are additionally rate-limited per ticker: a previously reviewed ticker is only eligible again after `review_cooldown_days` (default 2), and only while still below `max_reviews_per_30_days` (default 10). Slack single-ticker reviews bypass this screener gate. **New** = never reviewed; **review** = previously reviewed and past the autonomous guardrails. Targets `uninvestigated_target_pct` from the new pool. When the pool is exhausted (all instruments in cooldown), the fallback orders by `last_screened_at ASC` (least recently screened first) to rotate, but it still respects the autonomous review guardrails. **Proactive seed**: when eligible pool &lt; 2×max_candidates, seed instruments are merged to ensure rotation headroom.
5. **Curated seed universe & enrichment cascade** — `seed_universe.py` is derived from T212's instrument list (~6900 US equities, 100% tradeable). Regenerate with `poetry run python scripts/generate_seed_from_t212.py --from-db`. **Bulk enrichment:** one-off `poetry run python scripts/bulk_enrich_instruments.py` (parallel yfinance) to populate sector, market_cap, industry, business_summary, exchange, currency, name. **Backfill:** `poetry run python scripts/backfill_industry_summary.py` for instruments that already have sector+market_cap but lack industry/summary/name. Used as fallback when instruments table lacks enriched data; only enriches instruments present in DB (T212-available). Scheduled batch enrichment (`enrich_instruments_batch`) cascades: yfinance → Finnhub → Alpha Vantage OVERVIEW → BRAVE_ANSWERS; saves industry and business_summary when available. Tickers that fail yfinance OHLCV fetch are flagged `data_available=False` and permanently excluded.
5a. **Deferred Finnhub/AV (intraday)** — When `cycle_frequency: intraday`, screening uses `get_stock_analysis_lite` (yfinance only). Finnhub and Alpha Vantage are fetched only for `positions ∪ top_tickers` (active-review tickers), with `NewsSentimentCache` lookup first.
5b. **Web search fallback** — When Finnhub analyst data or Alpha Vantage ticker sentiment times out or fails, `get_news_sentiment_fallback` (Brave/Tavily) supplies analyst/news-like snippets for the strategy prompt. Controlled by `data_fallback_web_search_enabled`; respects search API monthly budget.
5c. **Queued ticker re-evaluation** — When opportunity is enabled, Phase 3 in `_fetch_stocks_data` re-adds queued tickers (from OpportunityQueue) to stocks_data each cycle, bypassing screening cooldown, so they can reach 2nd cycle and promote before expiring.
6. **Company profiles** — `longBusinessSummary` + `industry` from yfinance are persisted in the `Instrument` model and included in the Claude strategy prompt for qualitative reasoning. When yfinance returns sparse data, the orchestrator falls back to Instrument.industry and Instrument.business_summary (enriched by bulk/backfill scripts; ~5,477 instruments deployed).
7. **T212 order status** — Order status is derived from T212 API response `status`: FILLED/PARTIALLY_FILLED→filled, NEW/CONFIRMED/UNCONFIRMED/LOCAL→pending, REJECTED/CANCELLED→failed. Do not assume filled on 200 OK. **Write-before-execute**: market orders are recorded with status `"submitting"` before the T212 API call; updated to actual status after response. **No retry on POST/DELETE**: mutating T212 requests are never automatically retried (T212 has no idempotency keys). Only safe methods (GET) are retried. **`OrderManager.execute_market_order`** issues a **single** `place_market_order` call (no retry loop) so a timeout after the broker accepts cannot double-submit. **Failed execution payloads** (orchestrator trade alerts) still include `quantity`, `price`, and `value_gbp` when the intended size is known, plus the broker HTTP status/body snippet when Trading 212 rejects the request. **Order sync**: At the start of each cycle (non–dry-run), `OrderManager.sync_order_status_from_t212()` fetches T212 order history and updates local `Order.status` from pending to filled when T212 reports FILLED. **Stale pending market SELL cleanup**: when a later live cycle changes a ticker to `HOLD` or `QUEUED`, the orchestrator cancels any still-live pending market SELL for that ticker so an earlier pre-open exit does not survive the newer decision.
8. **Cost degradation** — FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED. When only Google is over budget, returns NO_GEMINI (GPT-4o still runs). When only OpenAI is over budget, returns NO_GPT4O (Gemini still runs). When both moderator budgets are exceeded, moderation is skipped. Individual moderators self-check their own budgets before each call. Budget per-provider per-day, plus monthly cap. **Research costs** tracked separately in `research_logs.cost_usd` ($0.005/paid call); surfaced in dashboard Costs page as a distinct "Agentic Research" band (daily chart + monthly table) alongside LLM and API costs. `/api/research/summary` returns cost breakdowns by member, tool, and provider.
9. **Order dedup** — 5-minute window prevents double-execution of the same order.
10. **Order value floor** — `min_order_value_gbp` is enforced as a minimum BUY ticket size: MARKET BUY and limit-BUY requests below the floor are upgraded to `min_order_value_gbp` when enough cash is available after the cash-floor guard; otherwise the BUY is skipped. Explicit market SELL decisions may execute below the floor so small positions can be fully exited. Protective stop-loss SELL orders are also allowed below the floor so small positions remain risk-protected. REDUCE still requires at least the floor unless it would leave a sub-£500 residual, in which case it is auto-converted to full SELL.
11. **Deterministic swing exits** — When `take_profit_full_sell_pct` is reached (default `15%` unrealized gain), the orchestrator upgrades the position to a full SELL before ordinary SELL/REDUCE handling. This take-profit path may bypass the ordinary 24h minimum-holding rule when `take_profit_allow_before_min_hold` is enabled. Residual positions below `small_position_cleanup_value_gbp` (default `£200`) are liquidated immediately in a pre-strategy deterministic pass with no strategy/moderation/risk LLM involvement for that ticker.
11. **Stop-loss / pending-order cleanup** — automatically placed after every BUY using Claude's `stop_loss_pct` (GTC validity). `place_stop_loss()` accepts optional `current_price_gbp` for GBP-denominated `value_gbp` logging when native price is USD. **Before SELL/REDUCE:** `OrderManager.cancel_conflicting_stops(ticker)` cancels any pending stop-loss orders for the ticker before placing the market order (T212 reserves shares for pending stops, blocking concurrent sells). **Idempotent cancel:** HTTP 404 and common 400/409 “already gone / not pending” responses are treated as success so the SELL can proceed. If cancellation fails with a non-idempotent error, the SELL is aborted. **SELL/REDUCE quantity** is clamped to `T212Client.get_position(ticker)` after stops are cleared to avoid oversize sells. **Newer HOLD/QUEUED overrides stale pending SELLs:** if a later live cycle decides not to exit, `OrderManager.cancel_pending_market_sells(ticker, reason)` cancels any still-live pending market SELL for that ticker and marks the local order row `cancelled`. For `liquidate_all()`, stop cancellation is fail-open. After REDUCE, `place_missing_stops()` re-places a stop for remaining shares in the same cycle.
12. **UOV optimizer guardrail** — UOV may reorder/queue BUYs, but it never directly triggers SELL/REDUCE. Strategy remains sell authority; Risk remains final veto.
12. **Notification fail-open** — alert delivery failures (Slack/Email) must never block trade execution.
13. **Intelligent order management** — `StopLossManager` runs after execution each cycle. Stop-loss is placed for BUY when `exec_result.status` in (filled, dry_run) — **not** for `pending` market orders, since T212 requires an existing position and returns 400 if the BUY hasn't filled yet (e.g. placed before market open). Pending BUYs are covered by `place_missing_stops()` in the next cycle once the position exists. **Place missing stops**: `place_missing_stops()` runs before reassessment; positions without a pending stop get one using `default_stop_loss_pct` (or ATR-based when available). Three capabilities:
    - **ATR-based stop reassessment**: Recalculates stops using 14-day ATR × configurable multiplier, clamped to [min, max] distance. By default only tightens (never widens).
    - **Software trailing stops**: Tracks high-water mark per position. Ratchets stop up as price rises. Implemented by cancel-then-replace: old stop cancelled first (T212 allows only one pending stop per instrument), new stop placed immediately after; if new placement fails an emergency stop at the old price is re-placed for protection. Ratchet is skipped when computed stop ≥ current price.
    - **Limit dip-buy orders**: When strategy outputs `entry_type: "limit_dip"`, places limit BUY below current price instead of market order. Offset % configurable globally or per-decision.
    - All adjustments logged to `stop_loss_adjustments` table and emitted as `order_adjustment` Slack notifications.
13. **Agentic research (US-4.4)** — When `research.enabled`, Strategy/Skeptic/Risk can use tools: `web_search`, `news_search`, `sector_search`, `sec_search` (SEC EDGAR), `macro_search` (macro-economic). Per-member caps 20/8/7, total 35/cycle. Brave primary, Tavily fallback. SEC EDGAR free. Pipeline shares a single `ResearchExecutor`/`ResearchBudget` across Strategy and Moderation for pipeline-wide cap enforcement. All three members (Strategy, GPT-4o Skeptic, Gemini Risk) have full tool-use loops. Latency and cost recorded per call. 37 unit tests. See `docs/AGENTIC_RESEARCH.md`.
14. **Dashboard backend (Phase 1 + Phase 1.5 + full API + UX Phases 1-3 + Evolution Planner)** — FastAPI REST API + SSE stream. Endpoints: runs, status (includes system state and paused), universe, portfolio, orders, events/stream; decisions (with pipeline waterfall), moderation, risk; opportunity (scores, queue, history); outcomes (list, stats); stop-loss (current, adjustments); performance (metrics, history); costs (daily, monthly, degradation); api-usage (daily); system (state, trigger-cycle, pause, resume, force-sell); chat session CRUD foundation; evolution planner routes under `/api/evolution/*`; POST /api/runs/trigger (dry-run), POST /api/runs/trigger-live (live cycle). All query agent SQLite read-only; no duplicate tables outside the dedicated evolution planner workflow tables. Event logger: non-blocking, fail-open. **Frontend UX (Phase 1):** AlertBanner (persistent alert aggregation on all pages — system state, SSE, degradation, losing positions, failed orders), Dashboard Home restructured (always-visible positions + activity feed, two-column layout, merged top cards, cycle summary, performance metrics card with Sharpe/win-rate), `useAsyncData` hook for independent section loading (each section fails independently), Pause/Resume toggle with confirmation modal, PAUSED gets distinct cyan badge. SSE lifted to App level and shared with AlertBanner + Dashboard via props. `aria-expanded` on all collapsible sections, `aria-live` on activity feed. Mobile nav closes on link click. **Frontend UX (Phase 2):** Force Sell button per position with confirmation modal + focus trap (`useFocusTrap`), FreshnessIndicator ("Updated Xs ago" with stale warning), PnlDisplay with directional arrows (▲/▼) + `aria-label` for colour-blind safety, chart colours aligned to design tokens, keyboard-accessible expandable rows. **Tooltip contrast update (2026-03-19):** Portfolio Sector Allocation tooltip now forces high-contrast styling and explicit GBP formatting to avoid unreadable dark-on-dark hover text. **Frontend UX (Phase 3):** Skeleton loading screens (DashboardSkeleton, TableSkeleton, SkeletonCard replacing LoadingSpinner), position sparklines (inline SVG per position with directional colouring), decision pipeline waterfall (Strategy→Moderation→Risk→Execution horizontal flow in LLM Output Panel), nav consolidation (desktop primary 5 plus `More` dropdown for secondary 6), mobile card layouts (Portfolio, responsive column hiding on Universe), `/universe/:ticker` deep-linking with URL search params (`?q=`, `?sector=`), typography hierarchy (`tracking-wide` on section headings). 28/28 UX audit findings resolved (score 6.5→9.0/10). Frontend: 11 pages — Dashboard Home, Universe (sortable columns, expandable rows with pipeline waterfall + full LLM outputs: strategy reasoning + extra fields + raw JSON, all moderators’ verdicts/reasoning, risk reasoning and rules), Run History, Portfolio (sparklines, Force Sell), Opportunity Pipeline, Order Management (Recent Orders + stop-loss levels + adjustments), Commands (Slack trade command audit log with stats cards, action/status filters, expandable rows), World News (macro regime + headline archive + action plan), Costs, Roadmap & Architecture (project timeline, architecture diagram), and Evolution Planner (authenticated operator-only natural-language change planning with clarification loop, validation matrix, repo context, and audit trail). When CAUTIOUS, "Reset Peak" button clears false drawdown. Order status reflects T212 response (filled/pending/failed). Universe table includes `Investigated`, `Reviews`, `Decisions`, `Holding`, `Sold`, and `UOV (ewma)` columns; `Sold` is the total number of shares sold based on executed and dry-run SELL orders only (orders store SELL quantities as negative, but the dashboard reports `abs(sum(quantity))`). For transparency, the backend also exposes a live vs dry-run breakdown per ticker so the UI can show cases where Sold > 0 comes entirely from hypothetical dry-run cycles with no live Trading 212 execution. The Universe `Research` column shows `latest cycle · total` counts so historical research is not confused with the latest decision context. Expanded Universe reasoning is scoped to the latest strategy cycle only; if the latest action is `HOLD` or `QUEUED`, moderation and risk correctly appear as "not invoked". Execution summary in that panel shows the latest recorded order activity across cycles, not necessarily an order from the displayed decision cycle. Cycle summary includes rejected_by_action (breakdown by strategy action: BUY, HOLD, QUEUED). For HOLD/QUEUED, moderation_consensus and risk_verdict are "not invoked"; rejection stages: strategy_hold, strategy_queued. Design: ZENOUZ.ai brand — bg #06060a, positive #00ffa3 (emerald), negative #ff4466, accent #00d4ff (cyan), violet #6332ff, Graph Theory Z logo. **Visual Design System (US-1.7.3):** Syne heading font (loaded via Google Fonts), full CSS token system (`--color-*`, `--shadow-panel/glow/glow-strong/card-hover`, `--radius-xs` through `--radius-lg`, `--transition-fast/base`), violet soft-fill accents, glass-dark `.card` treatment (radial-gradient + panel shadow + 1.5rem radius), brand gradient updated to violet→cyan→emerald, 72px violet atmospheric grid, Tailwind `font-heading`/`boxShadow.panel/glow`/`borderRadius.panel/hero` extensions. Sticky blurred nav with pill active state. Shared primitives: `Panel`, `MetricCard`, `StatusPill`, `SectionHeader`. Spec: `dashboard/frontend/dashboard-style-guide.md`. See `/branding/BRAND.md`, `docs/UX_AUDIT.md`, and `docs/ZEN_EVOLUTION_ENGINE.md` for findings and roadmap. Research API: `GET /api/research/logs`, `GET /api/research/ticker/{ticker}`, `GET /api/research/summary`. Evolution API: `GET/POST /api/evolution/requests`, `GET /api/evolution/requests/{id}`, `GET /plan`, `POST /messages`, `GET /runs`, `GET /artifacts`, `POST /approve-build`, `POST /approve-deploy`, `GET /deployments`; approvals intentionally return policy-gated blocks in `US-1.10`. Universe table includes a `Research` column showing per-ticker research call count; expandable rows include an **Agentic Research** block showing which pipeline member (Strategy/Skeptic/Risk) used which tool, the query, results summary, cache hit, provider, latency, and cost — enabling full transparency into how research influenced each decision. Config: `dashboard.enabled`, `dashboard.events_enabled`.

## Scheduling Architecture

The scheduler (`src/scheduler/scheduler.py`) creates one cron job per configured analysis-cycle entry. Intraday runs are timezone-aware and resolved from `cycle_times_local` in `America/New_York`; standard cadence continues to use fixed UTC times:

| `cycle_frequency` | Schedule source | `cycle_hours` | Use case |
|------------------|-----------------|---------------|----------|
| `intraday` | 10:00, 12:30, 15:15 America/New_York | 4 | 3 regular-session runs; DST-aware and aligned to the US market open/midday/late session |
| `standard` | 07:00, 19:00 UTC | 12 | Original 2-cycle cadence |

Other scheduled jobs (unchanged): daily snapshot 21:30 UTC, weekly report Fri 22:00 UTC, instrument refresh Sun 12:00 UTC.

**Market holiday skip:** When `skip_market_holidays: true` (default), analysis cycles are skipped on NYSE-observed holidays (New Year, MLK, Presidents' Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas). Implemented in `src/utils/market_holidays.py` using rule-based date computation (no external dependency).

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
  - `trade_without_stop` -> `["slack", "email"]`
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
- **formatters.py** — Channel-specific rendering (`render_event` → Slack/Email). Trade/queued messages include ticker, action, quantity (or "queued"), committee summary (Moderation=X | Risk=Y, or "—" when committee not invoked e.g. HOLD), reasoning excerpt, and structured stage reason for queued/filtered decisions. `format_trade_command_reply()` renders `SingleTickerResult` for Slack thread replies: review (full per-moderator verdicts with GPT-4o/Gemini scores and reasoning, no truncation), executed (with force-override indicator and overridden rules when applicable), rejected (full pipeline detail: price, strategy reasoning, per-moderator verdicts, risk triggered rules, force hint), error statuses.
- **service.py** — `NotificationService` with `emit_*` methods. Fail-open: all exceptions caught, logged with `exc_info`, and never propagated. Retries with backoff; failed attempts recorded in `notification_logs`.
- **slack_listener.py** — Socket Mode handler for inbound trade commands; resolves bot's own `user_id` via `auth.test` on startup and filters out self-messages (prevents cascading reply loops); processes review, direct-trade, strategy-triggered trade, and cancel commands in background threads; large-order confirmation flow with expiry for BUY/SELL; cancel commands execute immediately; console completion log after every command; graceful shutdown via `threading.Event`.
- **command_gateway.py** — Routes parsed `CommandRequest` to `SingleTickerRunner`, `DirectTradeRunner`, or `CancelCommandRunner`; resolves ticker(s) via `resolve_ticker_to_t212()`; propagates `error_message` and `rejection_reason` from runner result for Slack display.
- **trade_command_parser.py** — Regex-first NL parser with Claude fallback; extracts `command_kind`, `execution_mode`, action (BUY/SELL/REVIEW/CANCEL), ticker subject phrase(s), optional quantity/amount_gbp, cancel order class, and `force` flag from free-text Slack messages. Supports plain direct BUY/SELL, `review X and buy|sell`, `buy|sell X and trigger strategy`, and `cancel buy|sell|stop sell ...`. Force prefixes: `force buy`, `override buy`, `!buy`.
- **providers/** — Slack webhook, SMTP email. Providers implement `send(subject, body)` and raise on failure.
- **Event types**: `trade_instruction_approved`, `trade_execution_result`, `cycle_run_summary`, `state_transition`, `critical_cycle_failure`, `order_adjustment`, `trade_without_stop`

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
| `PortfolioSnapshot` | `portfolio_snapshots` | End-of-cycle portfolio state. `positions_json` stores normalised positions (ticker, quantity, value_gbp, pnl_gbp, pnl_pct) converted from T212 `instrument.ticker`; uses `walletImpact` when available, otherwise applies account-level GBP scaling from `account_summary.investments.currentValue` |
| `OpportunityScoreSnapshot` | `opportunity_score_snapshots` | Per-cycle UOV components and final/ewma scores per ticker |
| `OpportunityQueue` | `opportunity_queue` | Active queued BUY opportunities; `queue_status`: QUEUED → EXECUTING → EXECUTED |
| `PerformanceMetric` | `performance_metrics` | Daily/rolling Sharpe, Sortino, drawdown, win rates by strategy, alpha |
| `TradeOutcome` | `trade_outcomes` | Per-trade P&L linking BUY to SELL/REDUCE with conviction and moderator linkage |
| `StopLossAdjustment` | `stop_loss_adjustments` | Audit trail for stop-loss reassessments, trailing ratchets, and limit orders |
| `MacroState` | `macro_state` | Proactive macro scan snapshots: regime (RISK_ON/RISK_OFF/NEUTRAL), confidence_score, top_signals_json, action_plan_json, sector_summary, economic_highlights |
| `MacroSignalLog` | `macro_signal_logs` | Normalized audit log of individual macro signals linked to MacroState |
| `MacroHeadline` | `macro_headlines` | Persistent archive of Finnhub economic headlines with category, source, URL; dedup on (headline, published_at) |
| `EventsLog` | `events_log` | Real-time activity stream for dashboard SSE (event_type, source, message, metadata_json) |
| `Run` | `runs` | Run metadata (cycle_id, run_type, started_at, completed_at, status, summary_json) |

## Configuration (config/settings.yaml)

Key tuneable values:

- **Trading**: `mode`, `account_type: practice|live` (practice = relaxed state machine), `cycle_frequency: intraday|standard`, `schedule_mode: market_session|fixed_utc`, `schedule_timezone`, `cycle_times_local`, legacy `cycle_times_utc`, `skip_market_holidays: true` (NYSE holiday skip), `cycle_timeout_seconds: 1800` (30min default; prevents hung cycles), `max_positions: 15`, `cash_floor_pct: 10`, `min_order_value_gbp: 500` (minimum BUY ticket size; MARKET BUY and limit-BUY are upgraded to this floor when cash allows; REDUCE still uses it as a true floor; explicit market SELL and protective stop-loss exempt), `min_reduce_pct_of_position: 25`, `reduce_tiers_pct: [25, 50, 70, 100]`, `reduce_requires_gain_or_risk: true`, `reduce_min_unrealized_gain_pct: 10`, `take_profit_full_sell_pct: 15`, `take_profit_allow_before_min_hold: true`, `small_position_cleanup_enabled: true`, `small_position_cleanup_value_gbp: 200`, `fx_aware_quantity: true` (convert native-currency price to GBP for BUY quantity calculation using account-level FX scale)
- **Risk**: `min_holding_hours_before_reduce: 24`, `max_single_stock_pct: 15`, `max_sector_pct: 35`, `cautious_drawdown_pct: 30`, `halt_drawdown_pct: 40`
- **Strategy weights**: momentum `0.35`, mean_reversion `0.30`, factor `0.35`
- **Models**: `claude-sonnet-4-5-20250929` (strategy), `gpt-4o` + `gemini-2.5-flash` (moderation)
- **Universe**: `max_candidates: 35`, cap tiers 70/20/10% (large/mid/small), `screening_cooldown_hours: 12`, `effective_screening_cooldown_override: 4`, `review_cooldown_days: 2`, `max_reviews_per_30_days: 10`, `data_fallback_web_search_enabled`, `batch_enrichment_enabled`, `batch_enrichment_per_run`
- **Strategy**: One decision per ticker (up to 35). Actions: BUY, SELL, HOLD, REDUCE, QUEUED. Targets 60+ decisions/day (3 cycles × 20+ through full pipeline).
- **Data cache TTLs** (configurable): `ohlcv_indicators: 4h`, `fundamentals: 12h`, `finnhub_analyst: 6h`, `alpha_vantage_broad: 4h`, `macro_intelligence: 4h`
- **Cost**: Anthropic £1/day, OpenAI £0.75/day, Google £0.50/day, monthly cap £50; **search_api_limits**: 2,000 brave_search, 2,000 brave_answer, 1,000 tavily
- **Research** (US-4.4): `enabled`, `strategy_research_enabled`, `skeptic_research_enabled`, `risk_research_enabled`; caps 20/8/7 per member, 35 total/cycle
- **Opportunity**: `enabled`, `mode: shadow|active`, `immediate_threshold_z` (0.0), `queue_threshold_z` (-0.15), `queue_ttl_cycles` (6), swap delta, EWMA half-life, weighted feature map, stage penalties. Rejection reasons are structured (`awaiting_promotion`, `capacity_gated`, `below_immediate`, `below_queue`, `queue_expired`, `no_longer_eligible`). Queued tickers re-evaluated each cycle (Phase 3 in _fetch_stocks_data) bypassing cooldown.
- **Order management**: `enabled`, `default_stop_loss_pct: -8`, `reassess_stops`, `trailing_stops` (enabled, trail_pct), `limit_orders` (enabled, offset_pct, validity), ATR multiplier, min/max stop distance, only_tighten_stops
- **Notifications**: `enabled`, channels/routes, retry/timeout/dedup config, dry-run alert policy, command gateway flag (disabled in v1)
- **Dashboard**: `enabled`, `events_enabled`, `cors_origins` (list of allowed CORS origins; defaults to localhost when absent). Operator auth is session-based: set `DASHBOARD_OPERATOR_USERNAME`, `DASHBOARD_OPERATOR_PASSWORD_HASH`, `DASHBOARD_SESSION_SECRET`, and optionally `DASHBOARD_INSECURE_DEV_MODE=true` for localhost-only dev. All non-public `/api/*` routes require a valid signed operator session cookie; anonymous read-only routes live under `/api/public/*`. Frontend no longer injects secrets at build time. **Axios response interceptor** + **SSE 401/403** flip the SPA into signed-out state. **`GET /api/events/stream` uses `fetch()` + stream parsing (not `EventSource`)** with `credentials: 'include'`; exponential backoff on disconnect. Operator login is blocked over plain HTTP except localhost dev mode. `/api/orders/health` unresolved failures: cleared only by a later **filled** or **cancelled** order for the same `(ticker, action, order_type)` — not by `dry_run`.

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
| `docs/WORLD_NEWS_DASHBOARD.md` | World News dashboard tab: headline archival, macro regime display, API endpoints, categorisation |
| `dashboard/frontend/src/data/roadmap.ts` | Features delivered or added to pipeline — the dashboard Roadmap page reads milestone status from this file |

**How to update:** After implementing a feature, scan each file above for sections that reference the changed area. Update inline — do not leave stale descriptions. Keep the same tone and depth as the existing content.

**Test count:** Update `README.md` status line (`N tests passing`) whenever tests are added or removed.

**Dashboard roadmap:** The Roadmap & Architecture page (`dashboard/frontend/src/pages/Roadmap.tsx`) renders milestones from `dashboard/frontend/src/data/roadmap.ts`. When a user story is delivered, move it from `status: 'pipeline'` to `status: 'delivered'` with `start`/`end` dates. When a new pipeline story is added, append it to `MILESTONES` with `horizon` (`Next` / `Soon` / `Later`) and `timeboxDays` (`1` or `2`) so the default Timeline board stays readable and reflects the team’s short-cycle delivery pace. The architecture Mermaid diagram in `Roadmap.tsx` should also be updated when new pipeline components are added.

## Project Evolution Context

- **Current state:** POC v1.0 — deployed to VPS for live data collection on Trading 212 Practice
- **Development team:** Project Lead (PhD Maths, DS Manager), Claude Code Opus 4.6 (cloud, primary dev), Codex 5.3+ (local VS Code, secondary dev)
- **Principles:** Innovation, simplicity, elegance, transparency. No feature for technology's sake.
- **Key docs:** `docs/SOPHISTICATION_ROADMAP.md` (backlog), `docs/COMPETITIVE_ANALYSIS.md` (positioning)


## Near-term delivery focus (updated 2026-03-25)

**Delivered:**
- **US-1.5** Chat Interface & Real-Time Trade Alerts
- **US-5.1** Backtesting Engine (engine, walk-forward, promotion report)
- **US-1.8** Dashboard VPS Deployment
- **US-1.7** Dashboard full spec (full API + 10 core pages, later extended to the 11-page authenticated surface with the Evolution Planner workspace)
- **US-1.4** Deploy POC to VPS
- **US-4.4** Agentic Research — 5 tools, all 3 members have tool-use loops, shared pipeline-wide budget, 37 tests
- **US-7.0** Production Audit & Safety Fixes — 34 findings (3C/6H/12M/13L); Phase 1+2 delivered, see `docs/TRADING_SYSTEM_AUDIT.md`
- **US-7.1** Dashboard Authentication — session-based operator auth, secure cookies, explicit `/api/public/*` read-only routes, and frontend route guards
- **US-4.1** Volume Signals — `data_providers.volume_signals_enabled`; OBV + 20-day volume ratio in indicator output; momentum/mean-reversion scoring; moderator context surfaced; 6 new tests
- **US-7.4** Integration Test Coverage — shared in-memory orchestrator harness; `run_cycle()` dry-run happy path; orphaned decision surfacing; live ACTIVE → CAUTIOUS and HALTED liquidation transitions; manual reset recovery; 5 new tests
- **US-3.1** Risk-Parity Position Sizing — `risk.risk_parity_enabled`; 60-day inverse-vol BUY overlay with vol floor + target-vol scaler; strategy/risk waterfall exposes Claude size vs risk-parity size; BUY execution uses delta-to-target semantics; 10 new tests
- **US-1.7.3** Dashboard Visual Design System — Syne font; full CSS token system (`--color-*`, `--shadow-*`, `--radius-*`, `--transition-*`); glass-dark panels; 72px violet grid; brand gradient violet→cyan→emerald; blurred nav; pill active state; 4 shared primitives (`Panel`, `MetricCard`, `StatusPill`, `SectionHeader`); spec in `dashboard/frontend/dashboard-style-guide.md`
- **US-4.5** Proactive Macro Intelligence — daily scheduled `macro_scan` (configurable `macro_scan_time_utc`, default 06:00 UTC); persisted `MacroState` (regime/confidence/top_signals/action_plan) + `MacroSignalLog` audit trail; deterministic regime derivation (RISK_ON/RISK_OFF/NEUTRAL) with optional Claude-backed second-order reasoning; cycle-time injection into strategy prompt and moderation market context; 48h staleness guard on macro state injection; DataFetcher constructor injection for client reuse; 25 tests
- **US-1.7.4** World News Dashboard Tab — persistent `MacroHeadline` archive with keyword-based categorisation (fed, rates, trade, earnings, inflation, jobs, gdp, market); 5 REST endpoints (`/api/macro/*`); dedicated `/world-news` page with regime card, timeline, expandable headline feed with category filters, action plan, sector snapshot; compact macro conditions bar on Dashboard Home; no LLMs/Brave/Tavily needed; 23 new tests
- **US-1.6** Slack NL Trade Commands — inbound Slack Socket Mode commands now split into 4 modes: `review`, `direct_trade`, `strategy_trade`, and `cancel`. Plain BUY/SELL go through `DirectTradeRunner` (quote/preflight/confirmation/execution only), `review X and buy|sell` or `buy|sell X and trigger strategy` go through the full `SingleTickerRunner` committee path, and `cancel buy|sell|stop sell ...` goes through `CancelCommandRunner` with per-message broker cancellation audit. **Force buy/sell** (`force buy`, `!buy`, `override buy`) bypasses explicit moderation/risk blocks only on strategy-triggered Slack trades and is logged as `OVERRIDDEN`. Regex-first NL parser with Claude fallback; `SlackCommandLog` audit table now includes execution mode, cancel target class, target tickers, and result payload; `CommandGateway` dispatches by mode; `resolve_ticker_to_t212()` utility; large order confirmation flow for BUY/SELL; FX-aware GBP sizing for explicit `£` orders on `_US_EQ` / OTC names; graceful shutdown via `threading.Event`; console completion log after every command; reply formatter; CLI entry `poetry run python -m src.agents.notifications.slack_trade_listener`; Docker deploy includes an always-on `slack-listener` service
- **US-1.9** Conversational Trading WF skeleton — `ChatSession` + `ChatTurn` DB models with Alembic migration; `SessionManager` with real CRUD (create/add_turn/get/end); 4 dashboard REST endpoints (`/api/chat/sessions`, `/api/chat/sessions/{id}/turns`, `/api/chat/sessions/{id}`, `/api/chat/sessions/{id}/end`); no LLM/execution yet — plumbing for future multi-turn conversational workflow
- **US-1.10** Evolution Planner — separate evolution workflow domain (`evolution_requests`, `evolution_messages`, `evolution_plans`, `evolution_runs`, `evolution_artifacts`, `evolution_approvals`, `evolution_deployments`), authenticated dashboard Evolution page, deterministic intent normalization, repo-context retrieval, risk classification, validation matrix, clarification loop, and planner-only policy gates on build/deploy approval attempts

**Week 1 sprint (in-progress — see `docs/SPRINT_WEEK_1.md` for full detail):**
- **US-8.1** Open-Source Launch Prep — nested dir, remotes, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CI (Day 8)

**Deferred (await data or later sprint):**
- Calibration (US-2.1, US-2.2) — requires ~50 trades
- US-5.2 Parameter sensitivity harness

## Known issues (2026-03-20)

1. **Dashboard VPS deployment** — US-1.8 delivered; deployment checklist in `docs/DASHBOARD_DEPLOYMENT.md`. Public pages can be served at `http://VPS_IP:8000`, but operator login is intentionally blocked on raw HTTP; use HTTPS or an SSH tunnel/VPN for operator access. Activity feed SSE uses relative URL when the SPA is same-origin; authenticated deployments use fetch-stream + session cookies.
2. **Dry-run state mutation** — Fixed (commit `e5e6f46`). Dry-run no longer mutates drawdown state or skips screening.
3. **Duplicate Run per scheduled cycle** — Fixed. Scheduler now passes `scheduled_cycle_id` to orchestrator; one Run per cycle (scheduler creates, orchestrator updates).
4. **Finnhub timeouts in cloud VMs** — Finnhub API calls may time out in VPS/cloud environments due to network latency. Pipeline handles gracefully: analyst recommendations and insider sentiment are missing but cycle completes. See AGENTS.md.
5. **T212 DELETE empty-body causing SELL abort** — Fixed. T212 `DELETE /equity/orders/{id}` returns 200 with empty body; `response.json()` threw `JSONDecodeError`, tenacity retried into 404, `RetryError` blocked the SELL. Fix: `_request` returns `{}` for empty bodies; retry predicate skips 4xx; `cancel_conflicting_stops` unwraps `RetryError`.
6. **Agent logic audit (2026-03-20)** — `docs/AGENT_LOGIC_AUDIT.md`: 5 Critical + 7 High + 9 Medium + 6 Low findings. Phase 1 fixes delivered: MODIFY verdicts now count as conditional AGREE in consensus (C-1); CAUTION consensus applies 25% allocation reduction (C-2); conviction clamped [0,100], allocation clamped [0,max_single_stock_pct] (C-3); Gemini scores clamped [1,10] (C-4); orphaned "submitting" orders synced (C-5); risk-driven exits bypass min_positions (H-1); `entry_type` added to strategy prompt schema (H-2); strategy tool-use timeout increased to 120s (H-3); consensus logged on all moderator rows (H-4); repaired decisions validated for required fields (H-5); strategy decisions deduplicated by ticker (H-6). 36 new tests.
7. **Formal verification audit (2026-03-21)** — `docs/FORMAL_VERIFICATION_AUDIT.md`: State machine completeness, race conditions, invariants, crash recovery, DB atomicity. 3 Critical + 7 Warning + 8 Info findings. Phase 1 fixes: scheduler `max_instances=1` on all jobs (prevents concurrent cycles), resume warns about HALTED/CAUTIOUS state. Phase 2 fixes: `trade_without_stop` alert notification (P2-5); OpportunityQueue `queue_status` field with QUEUED→EXECUTING→EXECUTED lifecycle + orphan reconciliation at cycle start (P2-6); portfolio re-query before BUY phase after SELL/REDUCE (P2-4); decision chain integrity check at cycle end (P2-3). 18 new tests. Phase 3 roadmap: HALTED auto-recovery, market hours check. 12 invariants verified.
8. **Code review production-readiness fixes (2026-03-22)** — Fixed. Orders health endpoint (`/api/orders/health`) now catches `EnvironmentError`/T212 failures gracefully and returns `live_fetch_error` instead of crashing. Orchestrator `float()` type-safety hardened for T212 cash dict values (nested `.get()` could return `None`). Risk-parity config validated: `lookback_days >= 2`, `vol_floor >= 0`, `target_vol > vol_floor` (clamped with warning). Risk-parity `_risk_load` guards against negative sqrt input. Fallback path rounding inconsistency fixed. Dashboard orders health test mocks corrected.

When touching the dashboard track, keep `README.md`, `docs/ARCHITECTURE.md`, `docs/SOPHISTICATION_ROADMAP.md`, `docs/DASHBOARD.md`, and `docs/DASHBOARD_DEPLOYMENT.md` synchronized.
