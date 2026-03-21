# Investment Agent

Autonomous investment agent that trades via the Trading 212 API (Practice/Demo mode) using a multi-LLM strategy pipeline. Currently deployed as a **Proof of Concept (v1.0)** to gather live performance data, with a [sophistication roadmap](docs/SOPHISTICATION_ROADMAP.md) for systematic improvement based on evidence.

**Status:** POC — 387 tests passing (performance/trade-outcome, backtesting, order management, notifications, macro intelligence, 3-cycle scheduler, dry-run state isolation, dashboard backend, research router, search API tracker, daily/weekly reports, market holidays, opportunity optimizer edge cases, agent logic audit fixes), deployment-ready for VPS. Dashboard Phase 1 + Phase 1.5 Analytics Lite + UX Phase 1 complete. US-1.8 Dashboard VPS Deployment implemented (Docker, multi-stage frontend build, SPA fallback). See [Dashboard Deployment](docs/DASHBOARD_DEPLOYMENT.md) and [UX Audit](docs/UX_AUDIT.md).

## Architecture

```
Orchestrator (configurable: 3 cycles at 08/12/16 UTC or 2 at 07/19 UTC)
  ├── Market Data Agent    → yfinance + Finnhub + Alpha Vantage (per-ticker news)
  ├── Universe Screener    → Sector-balanced, cap-tiered candidate discovery
  ├── Strategy Agent       → Momentum + Mean Reversion + Factor → Claude Sonnet synthesis
  ├── Moderation Panel     → GPT-4o (skeptic) + Gemini (risk assessor) → consensus
  ├── Risk Agent           → Hard rules, VETO power, never overridden by LLMs
  ├── Opportunity Agent    → Universal Opportunity Value (UOV) scoring + ranked BUY queue
  ├── Execution Agent      → Trading 212 API: market orders + stop-loss + dedup
  ├── Notification Agent   → Slack webhook + SMTP email alerts + notification_logs audit trail
  └── Journal & Reporting  → Per-trade journals, daily + weekly reports
```

**State Machine:** ACTIVE → CAUTIOUS (>30% drawdown, configurable) → HALTED (>40% drawdown, liquidate all)

## Setup

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation)
- API keys: Trading 212, Anthropic, OpenAI, Google AI, Finnhub, Alpha Vantage

### Installation

```bash
# Clone and install
git clone <repo-url> && cd investment-agent
poetry install

# Configure environment
cp config/.env.example .env
# Edit .env with your API keys

# Initialize database
poetry run alembic upgrade head
```

### Configuration

Edit `config/settings.yaml` for trading parameters, risk limits, cost budgets, and model selection.

Key settings:
- **Trading:** `cycle_frequency` (intraday | standard), cycle times, position limits, cash floor
- **Risk:** drawdown thresholds, VIX limits, sector caps, correlation limits
- **Universe:** candidate count, sector balance, market-cap tiers, screening cooldown
- **Opportunity:** UOV mode (`shadow|active`), thresholds (`immediate_threshold_z`, `queue_threshold_z`), EWMA half-life, queue TTL, swap delta
- **Notifications:** channel routes, retries/timeouts, dedup window, dry-run alert policy
- **Cost:** daily per-provider budgets, monthly total cap
- **Models:** Claude Sonnet (strategy), GPT-4o + Gemini Flash (moderation)

## Usage

### Run a single cycle

```bash
# Dry run (no real trades)
poetry run python -m src.orchestrator.main --dry-run

# Live cycle
poetry run python -m src.orchestrator.main
```

### CLI commands

```bash
poetry run python -m src.orchestrator.main --status       # System status
poetry run python -m src.orchestrator.main --performance  # Performance metrics summary
poetry run python -m src.orchestrator.main --dashboard   # Dashboard: portfolio, metrics, costs, positions
poetry run python -m src.orchestrator.main --pause        # Pause trading
poetry run python -m src.orchestrator.main --resume       # Resume trading
poetry run python -m src.orchestrator.main --reset-peak   # Reset peak to current, clear CAUTIOUS if incorrect
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ  # Force sell
poetry run python -m src.orchestrator.main --report       # Generate daily report
poetry run python -m src.orchestrator.main --uov-diagnostic  # Run with UOV in shadow mode, emit scores for calibration
```

### Backtesting

```bash
# Run with real data (fetches from yfinance if data/backtest/ empty; caches to CSV)
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward

# Synthetic data (no network, fast sanity check)
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
poetry run python -m src.backtesting.main --scenario bull --synthetic
```

See [Backtesting](docs/BACKTESTING.md) (includes walk-forward validation and promotion report) for details.

### Run the scheduler (continuous)

```bash
poetry run python -m src.scheduler.scheduler
```

### Dashboard (Phase 1 + Phase 1.5 Analytics Lite)

Run the backend from the project root (so `src` and `dashboard` are importable):

```bash
# Start the dashboard API server (local dev)
poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000

# API at http://localhost:8000, OpenAPI docs at http://localhost:8000/docs
```

**Endpoints:**
- `GET /api/runs/`, `GET /api/runs/diff`, `GET /api/runs/cycle/{cycle_id}`, `POST /api/runs/trigger`, `POST /api/runs/trigger-live` — Run history and dry/live cycle trigger
- `GET /api/status/` — Next run, cycle_frequency, system state (ACTIVE/CAUTIOUS/HALTED), paused
- `GET /api/universe/`, `GET /api/universe/{ticker}` — Universe and instrument detail
- `GET /api/portfolio/`, `GET /api/portfolio/history` — Portfolio snapshot and history
- `GET /api/orders/` — Order history
- `GET /api/events/`, `GET /api/events/stream` — Event log and SSE stream
- `GET /api/decisions/`, `GET /api/decisions/waterfall`, `GET /api/decisions/{cycle_id}`, `GET /api/decisions/ticker/{ticker}` — Strategy decisions and pipeline waterfall
- `GET /api/moderation/{cycle_id}`, `GET /api/moderation/ticker/{ticker}` — Moderation logs
- `GET /api/risk/{cycle_id}` — Risk decisions
- `GET /api/opportunity/config/`, `GET /api/opportunity/scores/`, `GET /api/opportunity/scores/{cycle_id}`, `GET /api/opportunity/queue/`, `GET /api/opportunity/history/{ticker}` — UOV config, scores and queue
- `GET /api/outcomes/`, `GET /api/outcomes/stats` — Trade outcomes and aggregate stats
- `GET /api/stop-loss/current`, `GET /api/stop-loss/adjustments` — Stop-loss levels and adjustment history
- `GET /api/performance/metrics`, `GET /api/performance/history` — Performance metrics
- `GET /api/costs/daily`, `GET /api/costs/monthly`, `GET /api/costs/degradation` — Cost breakdown and degradation
- `GET /api/api-usage/daily` — API call counts and error rates
- `GET /api/system/state`, `POST /api/system/trigger-cycle`, `POST /api/system/pause`, `POST /api/system/resume` — System state and controls

**Configuration:** Set `dashboard.enabled: true` and `dashboard.events_enabled: true` in `config/settings.yaml`.

### Dashboard Frontend

**Brand:** ZENOUZ.ai — Graph Theory Z logo, cyan→emerald gradient, Outfit + JetBrains Mono typography, dark theme (`#06060a`). The frontend uses a shared page header across all tabs with a right-aligned hybrid Concept 1+2 bold Z mark rendered on transparent background (no card) for an embedded look. See `/branding/BRAND.md` for the full brand guide.

```bash
cd dashboard/frontend
npm install
npm run dev    # Dev server on http://localhost:3000 (proxies API)
npm run build  # Production build (outputs to dist/)
```

**Pages:** Dashboard Home (alert banner on all pages; system state badge with distinct PAUSED colour; Pause/Resume toggle; Dry Run/Live Run buttons; 4 metric cards — cycle timing, portfolio value, performance 30d, monthly summary; always-visible cycle summary, positions snapshot with P&L bars and sparklines, real-time activity feed; independent section loading via `useAsyncData`; skeleton loading screens), Stock Universe (searchable, sortable-by-column table with `Investigated`, `Reviews`, `Decisions`, `Holding`, `Sold`, `UOV (ewma)` columns plus expandable rows with pipeline waterfall visualisation and committee reasoning and **full LLM outputs** — strategy reasoning, exit conditions, news/market/portfolio text, raw JSON; all moderators’ verdicts and reasoning; risk reasoning and triggered rules; deep-linkable via `/universe/:ticker`). The Universe `Sold` metric is computed from both executed and dry-run SELL orders (SELL quantities stored as negative; the dashboard reports `abs(sum(quantity))`), and the detail panel shows whether any live BUY/SELL executions exist in Trading 212 for the ticker. Additional pages: Run History (timeline, run diff view), Portfolio (positions with inline sparklines, P&L chart, sector allocation, Force Sell per position), Opportunity Pipeline (UOV scores and queue; queue shows when/why queued, when action taken, action), Order Management (stop-loss levels and adjustment history), Costs (daily/monthly cost charts, degradation), Roadmap (project evolution timeline from day 0, topic-grouped milestones, architecture diagram with component-to-US mapping). 8 pages total. Navigation: primary 4 pages + “More” dropdown for secondary 4. UX: skeleton loading screens, mobile card layouts, responsive column hiding, `aria-expanded`/`aria-live` accessibility, focus-trapped modals, directional P&L arrows (▲/▼) for colour-blind safety. All 28 UX audit findings resolved (score 9.0/10). See `docs/UX_AUDIT.md` for full audit.

**Testing the dashboard:** Ensure `dashboard.enabled: true` in `config/settings.yaml`. Start the backend: `poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000`. Run the endpoint check: `poetry run python dashboard/backend/test_endpoints.py`. Then run the frontend (`npm run dev` in `dashboard/frontend` or open `http://localhost:8000` after `npm run build`). See `dashboard/backend/TESTING.md` for the full 8-page and API check.

**Docker:** `docker compose up -d` runs both agent and dashboard. Dashboard served at `http://YOUR_VPS_IP:8000` (port 8000). Activity feed (SSE) and Run History work when accessing via VPS IP — frontend uses relative API URLs. Use the **Dry Run** or **Live Run** buttons on Dashboard Home to trigger cycles, or: `docker exec -it investment-agent poetry run python -m src.orchestrator.main` (live); add `--dry-run` for dry-run.

**Schedule (configurable):**

| Job | When | Notes |
|-----|------|-------|
| Analysis cycles | Mon–Fri, from `cycle_times_utc` | `intraday`: 08:00, 12:00, 16:00 UTC (3 cycles). `standard`: 07:00, 19:00 UTC (2 cycles). |
| Daily snapshot | 21:30 UTC daily | Portfolio snapshot + daily report |
| Weekly report | Friday 22:00 UTC | End-of-week summary |
| Instrument refresh | Sunday 12:00 UTC | Update tradable universe from T212 |

Set `cycle_frequency: intraday` in `config/settings.yaml` for 3 cycles during market hours; use `standard` for the original 2-cycle cadence.

### Docker

```bash
# Build and run (agent + dashboard)
docker compose up -d --build

# Rebuild after code changes (e.g. dashboard updates)
docker compose up -d --build   # or: docker compose up -d --build dashboard

# View logs
docker compose logs -f investment-agent
docker compose logs -f dashboard

# Dashboard at http://localhost:8000 (or http://YOUR_VPS_IP:8000 on VPS)
# Activity feed: Dashboard Home page; Run History: runs table (one row per cycle; scheduled cycles use single Run, no duplicates)

# One-off live cycle (in addition to scheduler)
docker exec -it investment-agent poetry run python -m src.orchestrator.main

# One-off dry-run cycle
docker exec -it investment-agent poetry run python -m src.orchestrator.main --dry-run
```

## Chat Notifications (US-1.5 Delivered)

Outbound chat interface v1 is live with persistent audit logging.

- **Planned (US-1.6):** Inbound Slack natural language trade commands — e.g. "Buy 10 shares of AAPL", "Sell my position in TSLA", "Review MSFT". Triggers a full single-ticker pipeline (data → strategy → moderation → risk) with final decision overwritten by user intent; Risk can still veto. See [Chat & Commands](docs/CHAT_AND_COMMANDS.md).
- Channels (outbound): Slack webhook + SMTP email
- Event types:
  - `trade_instruction_approved`
  - `trade_execution_result`
  - `cycle_run_summary`
  - `state_transition`
  - `critical_cycle_failure`
  - `order_adjustment`
- Audit table: `notification_logs` (`sent|failed|skipped|deduped`)

Default low-noise routing profile:
- `trade_instruction_approved` -> Slack
- `trade_execution_result` -> Slack + Email
- `cycle_run_summary` -> Slack
- `state_transition` -> Slack + Email
- `critical_cycle_failure` -> Slack + Email
- `order_adjustment` -> Slack
- `include_dry_run_alerts: false`

### Slack + Email hookup (VPS)

1. Set `.env` values:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ALERT_EMAIL_FROM=alerts@yourdomain.com
ALERT_EMAIL_TO=ops@yourdomain.com
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASS=SG_xxx
SMTP_USE_TLS=true
```

2. Restart container:

```bash
docker compose down
docker compose up -d --build
```

3. Verify effective config:

```bash
docker compose exec investment-agent python -c "
from src.utils.config import get_settings
s=get_settings()
print(s.notification_include_dry_run_alerts, s.notification_routes.get('cycle_run_summary'))
"
```

4. Verify email/slack send attempts:

```bash
docker compose exec investment-agent python -c "
from sqlalchemy import text
from src.data.database import get_session
s=get_session()
rows=s.execute(text(\"\"\"
SELECT timestamp,event_type,channel,status,attempt_number,error_message
FROM notification_logs
ORDER BY id DESC
LIMIT 20
\"\"\")).fetchall()
print(*rows, sep='\n')
s.close()
"
```

## Testing

```bash
poetry run pytest -v                          # All tests
poetry run pytest tests/test_risk_manager.py  # Risk agent (43 tests)
poetry run pytest tests/test_execution.py     # Execution (22 tests)
poetry run pytest tests/test_strategy.py      # Strategy (17 tests)
poetry run pytest tests/test_moderation.py    # Moderation (21 tests)
poetry run pytest tests/test_cost_tracker.py  # Cost tracker (16 tests)
poetry run pytest tests/test_screening_cooldown.py  # Screening + seed universe (10 tests)
poetry run pytest tests/test_opportunity_scorer.py tests/test_opportunity_optimizer.py  # UOV scoring + optimizer (5 tests)
poetry run pytest tests/test_notifications_service.py tests/test_notifications_providers.py tests/test_notifications_formatters.py tests/test_notifications_integration.py  # Notifications (20 tests)
```

## Project Structure

```
src/
├── orchestrator/       # Main control loop + state machine
├── agents/
│   ├── market_data/    # yfinance, Finnhub, Alpha Vantage, per-ticker news, universe screener, seed universe
│   ├── strategy/       # Momentum, mean reversion, factor, Claude synthesis
│   ├── moderation/     # GPT-4o + Gemini investment committee (full data + strategy assessment)
│   ├── risk/           # Hard rules with VETO power
│   ├── opportunity/    # UOV scorer + optimizer (ranking, queueing, swap suggestions)
│   ├── execution/      # T212 client + order manager: market, stop-loss, dedup
│   ├── notifications/  # Slack/email alerts, routing/retries/dedup, notification logging
│   └── reporting/      # Trade journals, daily/weekly reports, performance tracker, trade outcome tracker
├── data/               # SQLAlchemy models, Alembic migrations
├── scheduler/          # APScheduler with persistent job store
├── backtesting/        # Engine, paper broker, io (yfinance fetch + CSV cache), walk-forward, promotion report
└── utils/              # Config, logger, cost tracker
docs/                   # Project documentation (including archived plans in docs/archived/)
├── AGENTIC_RESEARCH.md          # Agentic research: design, tool definitions, phases
├── AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md  # US-4.4 step-by-step checklist
├── FOLLOWUP_RESEARCH_ROUTING_PLAN.md  # Follow-up routing policy (static-first, materiality + complexity gates)
├── ARCHITECTURE.md              # System architecture and component diagrams
├── BACKTESTING.md               # Backtesting engine, walk-forward validation, promotion report
├── CHAT_AND_COMMANDS.md         # ChatOps: trade alerts, notification routing, planned commands
├── COMPETITIVE_ANALYSIS.md      # Assessment vs professional quant systems
├── DASHBOARD.md                 # Web dashboard architecture, phases, frontend/backend design
├── DASHBOARD_DEPLOYMENT.md      # Dashboard VPS deployment: Docker, port 8000, SPA fallback
├── DATA_EXPORT_RUNBOOK.md       # VPS-to-local data export with integrity checks
├── DATA_RATIONALE.md            # Every data point's purpose and keep/remove verdict
├── DEPLOYMENT.md                # VPS deployment and monitoring guide
├── GOVERNANCE.md                # Governance framework, 9 risk rules, cost controls, audit trail
├── LOCAL_SETUP.md               # Local setup guide (Trading 212 Practice)
├── ORDER_MANAGEMENT_PROJECT.md  # Stop-loss, trailing stops, limit dip-buy: design and config
├── PRESENTATION.md              # Project presentation and summary
└── SOPHISTICATION_ROADMAP.md    # Prioritised improvement roadmap
notebooks/
├── diagnostics.ipynb       # Component diagnostics: every pipeline step (Config → Backtesting → Walk-Forward) with expected outputs
├── research_api_investigation.ipynb  # Phase 0 baseline: provider/API capability + SEC EDGAR validation
├── research_api_decision_framework.ipynb  # Phase 0.2: routing policy benchmark (difficulty gating, action mode, provider policy)
├── enriched_instruments.ipynb  # Inspect enriched instrument data (sector, market_cap, industry, summary)
├── brave_api_smoke.py      # Manual smoke test for Brave Search + Answers APIs (requires API keys)
├── brave_tavily_comparison.py  # Compare Brave vs Tavily extraction (sector, market_cap)
└── enrichment_benchmark.py # Benchmark BRAVE_SEARCH vs BRAVE_ANSWERS vs TAVILY: cost, time, accuracy
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design, component diagrams, data flow
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) — prioritised user stories for systematic improvement
- [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md) — honest assessment vs professional quant systems
- [Governance](docs/GOVERNANCE.md) — 9 risk rules, security guardrails, cost controls, audit trail
- [Data Rationale](docs/DATA_RATIONALE.md) — every data point's purpose, decision path, and keep/remove verdict
- [Deployment](docs/DEPLOYMENT.md) — VPS setup, Docker, monitoring, alerts
- [Dashboard](docs/DASHBOARD.md) — web dashboard architecture, phases, frontend/backend design
- [Dashboard Deployment](docs/DASHBOARD_DEPLOYMENT.md) — VPS deployment: Docker, port 8000, SPA fallback
- [Chat & Commands](docs/CHAT_AND_COMMANDS.md) — trade alerts, notification routing, planned inbound commands
- [Backtesting](docs/BACKTESTING.md) — engine, walk-forward validation, promotion report
- [Order Management](docs/ORDER_MANAGEMENT_PROJECT.md) — stop-loss, trailing stops, limit dip-buy: design and config
- [Agentic Research](docs/AGENTIC_RESEARCH.md) — canonical architecture and conventions; [Implementation Plan](docs/AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md) — checklist; [Follow-up Routing Plan](docs/FOLLOWUP_RESEARCH_ROUTING_PLAN.md) — routing policy
- [Data Export Runbook](docs/DATA_EXPORT_RUNBOOK.md) — VPS-to-local export procedure with integrity checks
- [Local Setup](docs/LOCAL_SETUP.md) — local setup guide for Trading 212 Practice
- [Presentation](docs/PRESENTATION.md) — project overview and summary

## Risk Rules (never overridden by LLMs)

- No single stock > 15% of portfolio
- No single sector > 35%
- Portfolio avg pairwise correlation < 0.7
- 30% drawdown → CAUTIOUS mode; 40% → HALTED (liquidate all); configurable in settings
- VIX > 25: max 8% position; VIX > 35: max 5%
- Daily loss > 2%: no new buys for 24 hours
- Cash floor: always >= 10%
- Min 5 positions once invested (checked for SELL and REDUCE actions)
- CAUTIOUS mode: no new BUYs (only SELL/REDUCE/HOLD)

## Cycle Output

Each cycle returns a JSON result with:
- **trades** — executed trades with industry, market cap, business description, reasoning, allocation, moderation/risk verdicts, stop-loss
- **rejected_stocks** — stocks considered but not traded, tagged by the stage that blocked them (`strategy_hold`, `moderation_blocked`, `risk_reject`, `opportunity_queue`, `opportunity_filtered`) with company metadata, rejection reason, and UOV diagnostics (`uov_ewma`, `uov_z`) for opportunity stages
- **opportunity_ranking** — per-ticker UOV scores (`uov_raw`, `uov_z`, `uov_final`, `uov_ewma`) persisted each cycle
- **queued_candidates** — BUY opportunities held in the UOV queue when not executed immediately
- **swap_candidates** — non-executing suggestions where a candidate's UOV materially exceeds weakest held position
- **cost_summary** — LLM spend for the cycle

This enables immediate post-cycle review and long-term analysis of missed opportunities.

### Universal Opportunity Value (UOV)

The orchestrator computes a cross-cycle UOV for each assessed ticker:
- `uov_raw` — weighted hybrid score from sub-strategy signals, conviction, moderation/risk outputs, sentiment proxy, and market-cap proxy
- `uov_z` — cross-sectional z-score of `uov_raw` within the cycle
- `uov_final` — `uov_z` plus deterministic stage penalties (HOLD/BLOCKED/REJECT/RESIZE)
- `uov_ewma` — smoothed cross-cycle score (`half-life = 6 cycles` by default)

Execution behavior:
- `mode: shadow` — compute/log UOV and queue state but preserve legacy BUY execution ordering
- `mode: active` — rank approved BUYs by `uov_ewma`, execute top opportunities first, queue remaining candidates, and emit conservative swap suggestions (no autonomous SELLs)

## Order Types

- **Market orders** — BUY, SELL, REDUCE (partial sell) via T212 market order API
- **Stop-loss orders** — Automatically placed after BUY executions using Claude's `stop_loss_pct` (GTC validity)
- **£500 order floor** — Orders below `min_order_value_gbp` are skipped for BUY/REDUCE/limit paths; for MARKET BUYs the floor check uses the *target trade value* (pre quantity flooring) and the logged order value uses the target to avoid off-by-a-few-pence rounding dips. Explicit market SELL and protective stop-loss orders are allowed below the floor so small holdings can still be exited/protected
- **REDUCE floor safeguard** — If a REDUCE would leave a position below £500, execution is automatically converted to a full SELL
- **Order deduplication** — 5-minute window prevents double-execution
- **Ticker normalization** — plain symbols returned by strategy (e.g. `AAPL`) are normalized to T212 instrument IDs (e.g. `AAPL_US_EQ`) before execution when an unambiguous mapping exists

## Universe Screening

Each cycle discovers new candidates beyond existing positions:
- **Curated seed universe** — Derived from T212 instrument list (~6900 US equities, 100% tradeable). Regenerate with `poetry run python scripts/generate_seed_from_t212.py --from-db`. Bulk enrich sector/market_cap/industry/summary: `poetry run python scripts/bulk_enrich_instruments.py`. Backfill industry/summary for already-enriched: `poetry run python scripts/backfill_industry_summary.py`. Used as fallback when instruments table lacks enriched data.
- **Sector-balanced sampling** — minimum 3 candidates per sector to avoid concentration
- **Market-cap tiers** — 70% large cap ($10B+), 20% mid cap ($2B-$10B), 10% small cap ($300M-$2B)
- **Screening cooldown & mix** — stocks are stamped with `last_screened_at` after each screen and excluded for a cooldown window (configurable via `screening_cooldown_hours`), ensuring broader universe coverage across cycles. Within the eligible pool, `get_screened_universe()` targets a configurable share of fresh (never-investigated) tickers via `uninvestigated_target_pct` (default ~50%).
- **Data availability filtering** — tickers that fail yfinance OHLCV fetch are permanently flagged `data_available=False` and excluded from all future screens
- **Metadata enrichment** — sector, market_cap, industry, and business summary back-filled from yfinance into instruments table (~5,477 deployed). Strategy prompt falls back to Instrument when yfinance returns sparse data.
- **Company profiles** — `longBusinessSummary` from yfinance is included in the Claude strategy prompt so it can reason about competitive moats, regulatory exposure, and news impact
- Skipped in CAUTIOUS mode (no new positions allowed)

## Cost Management

LLM costs tracked per-call with daily/monthly budget enforcement:
- Anthropic (Sonnet): £1.00/day
- OpenAI (GPT-4o): £0.75/day
- Google (Gemini Flash): £0.50/day
- Monthly cap: £50.00

Graceful degradation: skip Gemini → skip GPT-4o → skip strategy cycle → halt

## Project Evolution

This is a **POC (v1.0)** designed to validate the architecture and begin collecting live performance data. The system will evolve through evidence-based phases:

1. **Phase 1 (Current):** Deploy POC, build performance tracking and trade outcome feedback loop
2. **Phase 2:** Calibrate conviction scores and strategy weights from live data (~50+ trades)
3. **Phase 3:** Portfolio-level intelligence (risk-parity sizing, regime detection)
4. **Phase 4:** Signal enhancement (volume, earnings calendar, sector rotation)
5. **Phase 5:** ~~Backtesting engine~~ — delivered (engine, walk-forward, promotion report, yfinance fetch + CSV cache)
6. **Phase 6:** ML-assisted improvements (only if justified by accumulated evidence)

See [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) for full details, timelines, and priority matrix.
