---
tags: [dashboard, frontend, api]
status: current
last_updated: 2026-03-13
---

# Dashboard System

> A real-time operational dashboard for the investment agent that provides full visibility into scheduled and manual runs, stock universe management, committee decisions, portfolio performance, and trading activity. Designed to be extensible for ML features (prediction models, backtesting, anomaly detection) in future phases.

## Purpose

The dashboard is the primary visualisation and monitoring surface for the investment agent. It enables:

- **Real-time visibility** into scheduled and manual cycles, decisions, and order execution
- **Committee transparency** — full pipeline reasoning from strategy through moderation and risk
- **Portfolio management** — current holdings, P&L attribution, sector allocation
- **Opportunity tracking** — UOV scoring, queue state, promotion history
- **Order auditing** — stop-loss adjustments, trailing stops, limit orders, execution trail
- **Cost monitoring** — LLM spend tracking, degradation state, API usage
- **Performance analysis** — win rates, Sharpe/Sortino, trade outcomes, attribution by committee member
- **Research transparency** (Phase D) — per-member research activity via `GET /api/research/logs`, `GET /api/research/summary`; cache hit rates; `research_call` events in SSE stream

---

## Current Status

### Implementation Timeline (2026-03-10)

| Component | Status | Notes |
|-----------|--------|-------|
| **FastAPI Backend** | Complete | REST for runs, status (incl. system state), universe, portfolio, orders, events; decisions, moderation, risk, opportunity, outcomes, stop-loss, performance, costs, api-usage, research (logs, summary); system (state, trigger, pause, resume); SSE stream. All read from agent SQLite; no duplicate tables. |
| **Database Models** | Complete | `events_log` + `runs` tables with Alembic migration; backend queries existing agent tables only |
| **Event Logger** | Complete | Non-blocking, fail-open, background thread + queue |
| **Agent Instrumentation** | Complete | Scheduler + orchestrator emit events throughout pipeline |
| **React Frontend** | Complete | **8 pages:** Dashboard Home (system state badge ACTIVE/CAUTIOUS/HALTED, paused), Universe, Run History, Portfolio, Opportunity Pipeline, Order Management, Costs, Roadmap & Architecture. Design: dark #0d1117, neutral #58a6ff, accent #d4a017, subtle grid texture. UX improvements (2026-03-13): active nav state, mobile hamburger menu, loading spinner, error handling with retry, button consistency, sticky table headers, card shadow, focus styles. See `docs/DASHBOARD_DESIGN_REVIEW.md`. |
| **Config** | Complete | `dashboard.enabled`, `dashboard.events_enabled` in settings.yaml |

### Phase 1.5 Analytics Lite (delivered)

- Decision Explorer v1: expandable Universe rows with committee reasoning (strategy, moderation, risk) and full LLM outputs (strategy full text + raw JSON, all moderators' reasoning, risk reasoning and rules)
- Run-to-run diff: compare positions between two runs (new, closed, size changes)
- Top-bar: next run countdown, P&L summary

### Deployment (delivered)

See `docs/DASHBOARD_DEPLOYMENT.md` — Docker service, multi-stage frontend build, SPA fallback, port 8000. Activity feed (SSE) uses relative URL — works when accessing at `http://VPS_IP:8000`. Deploy to VPS.

### Stabilisation (done)

All test failures fixed, frontend-backend type alignment complete, API URLs corrected, trigger endpoint implemented. See [Known Issues and Fixes](#known-issues-and-fixes) below.

---

## Architecture

### Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              React Frontend (Vite) — 8 pages                                  │
│  ┌─────────┬─────────┬─────────┬───────────┬───────────┬─────────┬────────┬────────┐ │
│  │ Home    │ Universe│ Run Hist│ Portfolio │ Opportunity│ Order   │ Costs  │ Roadmap│ │
│  │ (state) │         │         │           │ Pipeline  │ Mgmt    │        │ & Arch │ │
│  └─────────┴─────────┴─────────┴───────────┴───────────┴─────────┴────────┴────────┘ │
│         Recharts / TanStack Table / dark terminal design (#0d1117, etc.)     │
└──────────────────┬──────────────────────────────────────────────────────────┘
                    │ REST + Server-Sent Events (SSE)
┌──────────────────┴──────────────────────────────────┐
│            FastAPI Backend (Python)             │
│  ┌────────────┬──────────────┬─────────────────┐ │
│  │  REST API  │  SSE Stream  │  Background     │ │
│  │  Endpoints │  Real-time   │  Event Logger   │ │
│  └────────────┴──────────────┴─────────────────┘ │
│                    SQLite (Agent DB)               │
└──────────────────┬──────────────────────────────┘
                    │ reads from
┌──────────────────┴──────────────────────────────┐
│         Existing Investment Agent Core           │
│  Scheduler → Committee → Orders → Notifications  │
└─────────────────────────────────────────────────┘
```

### Tech Stack

| Layer     | Choice                   | Rationale                                                  |
|-----------|--------------------------|-------------------------------------------------------------|
| Frontend  | React + Vite + Tailwind  | Fast dev, component ecosystem, pairs with Recharts/D3       |
| Backend   | FastAPI                  | Already Python stack, async-native, auto-generated API docs |
| Database  | SQLite (current) → Postgres (future) | Zero config for VPS, upgrade path when needed |
| Real-time | Server-Sent Events (SSE) | Simpler than WebSockets for one-way push updates            |
| Hosting   | Same Hetzner VPS         | Co-located with agent, nginx reverse proxy                  |

---

## Frontend Pages

### Page 1: Dashboard Home (Operations Hub)

**Top metrics bar:**
- System state badge: ACTIVE / CAUTIOUS / HALTED (from `system_state`). When CAUTIOUS, a "Reset Peak" button appears to clear false drawdown and return to ACTIVE.
- Last cycle timestamp + next scheduled cycle countdown
- Portfolio total value + daily P&L (from latest `portfolio_snapshots`)
- Cost burn: today's LLM spend vs daily budget (from `cost_logs`)
- Degradation level: FULL / NO_GEMINI / NO_GPT4O / etc.

**Activity feed (real-time via SSE):**
- Scrolling feed from `events_log` — run_started, universe_updated, decision_made, order_placed, order_executed, notification_sent, order_adjustment, research_completed
- Each event shows: timestamp, type icon, source, message, expandable metadata
- `universe_updated` message format: `Screened X/Y candidates (large=a/b, mid=c/d, small=e/f) — reviews: R, new: N | P in portfolio | cumul: S screened, V reviewed, O orders` where X=selected, Y=total available, a/c/e=per-tier selected, b/d/f=per-tier pool size, R=review count (investigated 24–48h ago), N=new investigations, P=positions re-evaluated; cumul = lifetime: S=instruments ever screened, V=distinct tickers ever reviewed by strategy, O=total orders placed
- Filter by event type, ticker, source

**Quick actions:**
- Dry Run and Live Run buttons (POST /api/runs/trigger, POST /api/runs/trigger-live); Live Run requires confirmation
- Pause/Resume trading
- Force sell a position

### Page 2: Stock Universe Explorer

**Main table (from `instruments`):**
- Sortable columns: click any header to sort by that column (ticker, name, sector, industry, market cap, last screened, status, investigated, reviews, holding, sold, UOV ewma)
- Columns: ticker, name, sector, industry, market_cap tier, last_screened_at, data_available
- Colour-coded labels based on latest committee verdict (from most recent `strategy_decisions` + `risk_decisions`)
- Screening cooldown indicator (greyed out if within 72h window)
 - `Sold` column: total number of shares sold per ticker based on executed **and dry-run** SELL orders, with the backend exposing a live vs dry-run split so the UI can highlight when Sold > 0 is driven entirely by hypothetical dry-run cycles.

**Ticker detail panel (expand/drill-down):**
- Latest committee trail: Strategy decision → Moderation scores → Risk verdict → UOV score
- Execution summary: most recent BUY/SELL orders for the ticker (quantity, status, timestamp), so reviewers can see whether BUY decisions actually resulted in Trading 212 orders or remained hypothetical (dry-run only or blocked before execution)
- Historical decisions: timeline of all past evaluations for this ticker
- Research trail (Phase D): what each member searched for this ticker, key findings
- Company profile: business summary, sector, industry (from `instruments`)

**Filters:**
- Sector, market cap tier, label (buy/sell/hold/watch/queued), date range
- "Show only queued" — tickers in `opportunity_queue`
- "Show only active positions" — cross-reference with portfolio

### Page 3: Run History & Decision Explorer

**Timeline view:**
- Calendar/timeline of all cycles (from `runs`) — scheduled vs manual, duration, status
- One Run per cycle: scheduled cycles use a single Run (scheduler creates with `scheduled_YYYYMMDD_HHMMSS`, orchestrator updates on completion; no duplicate cycle_ vs scheduled_ entries)
- Visual indicator for cycles that triggered trades vs no-action cycles
- Click to expand a run

**Run detail view:**
- Stocks reviewed in this run (from `strategy_decisions` where cycle matches)
- For each stock: full pipeline waterfall

```
Strategy (Claude) → conviction 0.8, action BUY
  └─ Moderation (GPT-4o) → skeptic score 0.6, approved
  └─ Moderation (Gemini) → risk score 0.7, approved
  └─ Risk Manager → PASSED (no rules triggered)
  └─ UOV → uov_final 1.4, rank #2
  └─ Execution → market BUY 10 shares @ $187.42
  └─ Stop Loss → set at $178.05 (5% below entry)
```

- Research activity summary (Phase D): queries made, cache hits, cost
- Rejected stocks: which stage blocked and why; `rejected_by_action` breakdown (BUY, HOLD, QUEUED); for HOLD/QUEUED, moderation_consensus and risk_verdict show "not invoked"

**Run comparison:**
- Select two runs side by side
- Visual diff: which tickers changed verdict between runs and why

### Page 4: Portfolio & Performance

**Summary cards:** Cash Balance, Investments (`invested_gbp`), Positions count, Last Updated.

**Current positions (from `portfolio_snapshots.positions_json`; normalised from T212 `instrument.ticker` / `walletImpact`):**
- Table: ticker, sector, quantity, value (GBP), P&L (GBP), P&L %
- Sector allocation pie chart (from position values; zero-value sectors filtered)
- Portfolio value history line chart (chronological: oldest left, newest right; rightmost point = latest snapshot)

**Historical performance (from `performance_metrics`):**
- Portfolio value over time (line chart, daily)
- Rolling Sharpe ratio, Sortino ratio
- Drawdown chart with state transitions marked (CAUTIOUS/HALTED thresholds)
- Win rate by strategy type (momentum/mean_reversion/factor)
- Alpha vs benchmark (if tracked)

**Trade outcomes (from `trade_outcomes`):**
- Closed trade table: ticker, entry date/price, exit date/price, P&L, holding period, conviction at entry, moderator scores
- Scatter plot: conviction vs actual return (does higher conviction = better returns?)
- Performance attribution: which committee member's signals correlated with best/worst trades

### Page 5: UOV & Opportunity Pipeline

**Current opportunity queue (from `opportunity_queue`):**
- Columns: Ticker, UOV (z), UOV (EWMA), Queued cycles, **When queued** (created_at), **Why queued** (awaiting promotion / capacity gated / below immediate), **Action** (BUY), **When action taken** (promotion/expiry logic)
- Queue config (TTL, thresholds) from GET /api/opportunity/config/

**UOV score evolution (from `opportunity_score_snapshots`):**
- Per-ticker UOV components over time: raw, z-score, final, EWMA
- Heatmap: all tickers × last N cycles, coloured by UOV score
- Identify patterns: which tickers are trending up in UOV (building conviction across cycles)

### Page 6: Order Management & Stop Loss Audit

**Recent orders (from `orders`):**
- Table of all recent orders: time, ticker, action, quantity, order type, status (filled/pending/dry_run/failed)
- Market orders (BUY/SELL/REDUCE) and stop orders in one view
- Status reflects T212 API response when live (FILLED→filled, NEW→pending, REJECTED→failed)
- `pending` has two common meanings in this table:
  - market order accepted but not yet executed (`type=MARKET`, typically `status=NEW`, common outside market hours)
  - working protective stop (`type=STOP`, remains `NEW` until stop price is hit or order is cancelled/replaced)
- Local DB statuses are reconciled at the start of each non-dry-run cycle via `sync_order_status_from_t212()` (pending -> filled when T212 reports FILLED/PARTIALLY_FILLED).

**Current stop-loss levels (from `orders` + `stop_loss_adjustments`):**
- Current stop-loss levels for all positions with distance from current price
- Trailing stop tracking: high-water mark, current trail level, visualised on a mini price chart
- Limit dip-buy orders: pending limits with entry target vs current price

**Adjustment history:**
- Table: timestamp, ticker, adjustment_type (reassess/trail/limit), old_value, new_value, reason
- Chart: stop-loss level evolution vs price for a selected position

### Page 7: Cost & API Monitoring

**Cost split: API vs LLM (daily and monthly):**
- Dashboard Home "This month" card: Runs, Cost (API/LLM split), Portfolio (start→end), P&L, New tickers investigated; collapsible daily cost table for last 7 days.
- Dashboard Home "Cumulative" card (separate): Screened, Investigated, Uninvestigated, Orders — lifetime stats. Uninvestigated = eligible instruments never reviewed by strategy.
- Costs page: daily chart stacks API (Brave/Tavily) + LLM (Anthropic, OpenAI, Google); monthly table has API, LLM, and per-provider columns
- API cost is estimated from `api_logs` call counts × published rates (Brave, Tavily); LLM cost from `cost_logs`

**LLM costs (from `cost_logs`):**
- Daily spend by provider (Anthropic, OpenAI, Google) — bar/area chart
- Monthly cumulative vs £50 cap — progress bar
- Degradation history: when did the system drop from FULL to NO_GEMINI, etc.
- Cost per trade: total LLM cost ÷ trades executed

**API usage (from `api_logs`):**
- Calls per provider per day (T212, Finnhub, AV, brave_search, brave_answers, tavily)
- Error rates and latency percentiles
- Rate limit proximity warnings

**Research costs (Phase D, from `research_logs`):**
- Per-member research spend
- Cache hit rate over time
- Most-queried tickers and topics

### Page 8: Roadmap & Architecture

**Tabbed layout:** `[Gantt | Roadmap | Architecture]` (default: Gantt)

**Gantt tab:**
- Mermaid Gantt chart: timeline of delivered work (green) and planned pipeline (grey)
- Sections by topic; nominal dates for pipeline items based on effort

**Roadmap tab:**
- Project evolution from day 0 (2026-02-22) to now; days-in-development counter
- Summary cards: 11 delivered · 14 pipeline · 44% complete
- Topic filter: All, Foundation, Calibration, Portfolio & Risk, Signals, Validation, ML / Advanced
- Vertical timeline grouped by topic; delivered (● green) vs pipeline (○ grey)
- Expandable milestone details: description, effort, priority, architecture components

**Architecture tab:**
- Pipeline diagram (Mermaid) with component-to-US mapping
- Links to `docs/ARCHITECTURE.md` and `docs/SOPHISTICATION_ROADMAP.md` served via `GET /api/docs/ARCHITECTURE` and `GET /api/docs/SOPHISTICATION_ROADMAP`

**Docs links:** In-app modal fetches and displays ARCHITECTURE.md and SOPHISTICATION_ROADMAP.md (avoids new-tab issues).

**URL:** `/roadmap`; optional `?tab=gantt`, `?tab=roadmap`, `?tab=architecture` for direct linking.

### Page 9: Research Explorer (Phase D — Agentic Research)

**Per-cycle research summary:**
- Total searches by member, cache hit rate, total cost
- Key findings that influenced decisions (tagged in `research_logs`)

**Per-ticker research trail:**
- Timeline: what each member searched for this ticker, what they found
- Research influence: did the research change the decision? (compare pre-research conviction if tracked)

**Research diversity metrics:**
- Query overlap between members (should be low — they have different mandates)
- Which member's research most often changed outcomes

---

## API Endpoints

The backend exposes the following endpoints. All query the agent's existing SQLite tables directly (no duplication).

### Activity & Runs

Runs fetched via `GET /api/runs/` or run-feed are **auto-reconciled**: any run stuck in "running" for >15 min with `strategy_decisions` is marked "completed" before returning. See `docs/DEPLOYMENT.md` §9.5.

```
GET /api/runs/                      # All runs, paginated, filterable by type/date
GET /api/runs/{run_id}              # Single run details
GET /api/runs/{run_id}/decisions    # Decisions for a specific run
POST /api/runs/trigger              # Trigger dry-run cycle
POST /api/runs/trigger-live         # Trigger live cycle (executes real trades)
POST /api/system/trigger-cycle      # Alias for dry-run trigger
```

### Universe

```
GET /api/universe/                  # All instruments, paginated, filterable
GET /api/universe/{ticker}          # Single ticker details with latest decisions
```

### Portfolio

```
GET /api/portfolio/                 # Current portfolio snapshot
GET /api/portfolio/history          # Historical snapshots for charting
```

### Orders

```
GET /api/orders/                    # All orders, paginated, filterable by status/date
```

### Committee Decisions

```
GET /api/decisions/                 # All decisions, paginated, filterable by ticker/cycle/action
GET /api/decisions/{cycle_id}       # All decisions for a specific cycle
GET /api/decisions/ticker/{ticker}  # Decision history for a ticker
```

### Moderation

```
GET /api/moderation/{cycle_id}      # Moderation logs for a cycle
GET /api/moderation/ticker/{ticker} # Moderation history for a ticker
```

### Risk

```
GET /api/risk/{cycle_id}            # Risk decisions for a cycle
```

### UOV & Opportunity

```
GET /api/opportunity/scores/        # Latest UOV scores, paginated
GET /api/opportunity/scores/{cycle_id} # Scores for a specific cycle
GET /api/opportunity/config/        # Queue TTL, thresholds (for display)
GET /api/opportunity/queue/         # Current opportunity queue
GET /api/opportunity/history/{ticker} # UOV score history for a ticker
```

### Trade Outcomes

```
GET /api/outcomes/                  # Closed trade outcomes, paginated
GET /api/outcomes/stats             # Aggregate stats (win rate, avg P&L, etc.)
```

### Stop Loss & Order Management

```
GET /api/stop-loss/current          # Current stop-loss levels for all positions
GET /api/stop-loss/adjustments      # Adjustment history, paginated
```

### Performance

```
GET /api/performance/metrics        # Latest performance metrics
GET /api/performance/history        # Historical metrics for charting
```

### Costs

```
GET /api/costs/daily                # Daily cost breakdown by provider
GET /api/costs/monthly              # Monthly cumulative
GET /api/costs/degradation          # Degradation state history
```

### API Usage

```
GET /api/api-usage/daily            # API call counts and error rates
```

### Research (Phase D)

```
GET /api/research/cycle/{cycle_id}  # Research activity for a cycle
GET /api/research/ticker/{ticker}   # Research history for a ticker
GET /api/research/stats             # Aggregate research metrics
```

### System Control

```
GET /api/system/state               # Current system state (ACTIVE/CAUTIOUS/HALTED), paused flag
POST /api/system/pause              # Pause trading
POST /api/system/resume             # Resume trading
POST /api/system/reset-peak         # Reset peak to current, clear CAUTIOUS if incorrect
```

### Documentation (served as Markdown)

```
GET /api/docs/ARCHITECTURE          # docs/ARCHITECTURE.md
GET /api/docs/SOPHISTICATION_ROADMAP # docs/SOPHISTICATION_ROADMAP.md
```

### Real-time Events

```
GET /api/events/stream              # Server-Sent Events (SSE) stream of activity
```

---

## Data Model

**Design approach:** Query the agent's existing SQLite database directly. No duplicate tables. Dashboard backend connects to the same `src/data/database.py` SQLite file used by the orchestrator.

### Core Table Mapping

| Dashboard View | Agent Table(s) | Notes |
|---|---|---|
| Activity Feed | `events_log` | Already populated by event logger ✅ |
| Run History | `runs` + `events_log` | Run metadata + per-run events ✅ |
| Stock Universe | `instruments` | Sector, industry, market_cap, business_summary, last_screened_at, data_available |
| Committee Decisions | `strategy_decisions` + `moderation_logs` + `risk_decisions` | Full pipeline trail per ticker per cycle |
| Portfolio | `portfolio_snapshots` + `orders` | Snapshots for history, orders for current state. `positions_json` stores **normalized** positions (ticker, quantity, value_gbp, pnl_gbp, pnl_pct) — orchestrator converts from T212 `instrument.ticker` and `walletImpact` before saving. Dashboard router supports both normalized and legacy T212 format for backward compatibility. |
| P&L / Trade Outcomes | `trade_outcomes` | Links BUY→SELL with P&L, conviction, moderator scores |
| UOV Scoring | `opportunity_score_snapshots` + `opportunity_queue` | Per-cycle UOV components, queue state |
| Order Management | `orders` + `stop_loss_adjustments` | Stop-loss audit trail, trailing stops, limit orders |
| Performance | `performance_metrics` | Sharpe, Sortino, drawdown, win rates, alpha |
| Cost Tracking | `cost_logs` | Per-provider per-call costs, degradation state |
| Notifications | `notification_logs` | Sent/failed/skipped/deduped attempts |
| API Usage | `api_logs` | External API call audit (T212, Finnhub, AV, brave_search, brave_answers, tavily) |
| Research (Phase D) | `research_logs` | Per-member research queries, cache hits, findings |
| Backtesting | `backtests/results/` (filesystem) | Walk-forward reports, promotion results |

### New Tables (Dashboard Only)

| Table | Purpose | Schema |
|-------|---------|--------|
| `events_log` | Real-time activity stream | `id`, `timestamp`, `event_type`, `source`, `message`, `metadata_json` |
| `runs` | Run metadata | `id`, `type` (scheduled\|manual), `started_at`, `completed_at`, `status`, `summary_json` |

---

## Design Tokens

### Colour Palette

| Token | Hex | Usage |
|-------|-----|-------|
| **Background** | `#0d1117` | Main canvas, dark charcoal terminal aesthetic |
| **Gain** | `#00ff88` | Positive P&L, bullish signals, "up" indicators |
| **Loss** | `#ff4444` | Negative P&L, bearish signals, "down" indicators |
| **Neutral** | `#58a6ff` | Info, neutral states, secondary metrics |
| **Accent** | `#d4a017` | Key metrics, highlights, important controls |

### Typography

- **Numbers/codes**: Monospace (JetBrains Mono or IBM Plex Mono)
- **Labels/headings**: Clean sans-serif (Inter, Roboto, SF Pro Display)

### Visual Style

- Dark charcoal background with subtle grid/scan-line texture for depth
- All numbers in monospace
- Dashboard aesthetic: Bloomberg terminal meets modern data dashboard

---

## Implementation Prompts

These are the Claude Code prompts used to build the dashboard. Revised prompts from PLAN_PATCH supersede the originals.

### Prompt 1: Extend Backend

```
Read Claude.md and README.md.

The dashboard backend exists at dashboard/backend/ with FastAPI, SSE events,
and basic routers for runs, universe, portfolio, orders, and events.

Extend the backend to expose the full agent data model for the frontend.
The frontend will query the agent's existing SQLite tables directly — do NOT
create duplicate tables.

Add the following routers:

1. routers/decisions.py — query strategy_decisions, moderation_logs,
   risk_decisions tables. Support filtering by cycle_id, ticker, action,
   date range. Include a "pipeline waterfall" endpoint that joins all three
   for a given ticker + cycle.

2. routers/opportunity.py — query opportunity_score_snapshots and
   opportunity_queue. Support UOV score history per ticker.

3. routers/outcomes.py — query trade_outcomes. Include aggregate stats
   endpoint (win rate, avg P&L, avg holding period, best/worst trades).

4. routers/stop_loss.py — query stop_loss_adjustments. Include current
   levels for all positions (join with orders table).

5. routers/performance.py — query performance_metrics. Support historical
   series for charting.

6. routers/costs.py — query cost_logs. Daily/monthly breakdowns by provider.
   Include degradation state from system_state table.

7. routers/system.py — GET system state, POST trigger cycle, POST pause,
   POST resume. These should call the existing orchestrator CLI logic
   programmatically (not shell out to subprocess).

All endpoints should support pagination (offset/limit), date range filtering,
and return Pydantic response models. Add proper OpenAPI descriptions.

The backend should connect to the agent's SQLite database (same file), NOT a
separate dashboard database. Use read-only sessions for query endpoints.

Update Claude.md and README.md.
```

### Prompt 2: Frontend MVP

```
Read Claude.md and README.md.

Create the React frontend for the investment agent dashboard at
dashboard/frontend/.

Design direction: Dark theme, financial terminal aesthetic. Think Bloomberg
terminal meets modern data dashboard. Monospace font for numbers, clean
sans-serif for labels. Colour palette: dark charcoal background (#0d1117),
electric green (#00ff88) for gains, warm red (#ff4444) for losses, cool
blue (#58a6ff) for neutral/info, muted gold (#d4a017) for key metrics.
Subtle grid/scan-line texture on background for depth.

Build these pages:

1. Dashboard Home — system state badge, metrics bar (portfolio value,
   daily P&L, cost burn, degradation level), real-time activity feed via
   SSE, quick portfolio summary cards.

2. Stock Universe — searchable/sortable table from /api/universe with
   committee verdict labels, screening cooldown indicator. Click to
   expand ticker detail with full pipeline waterfall (strategy →
   moderation → risk → UOV → execution).

3. Run History — timeline of all cycles, click to drill into decisions,
   rejected stocks with rejection stage. Run comparison view.

4. Portfolio & Performance — positions table with P&L, sector allocation
   chart, historical portfolio value line chart, rolling Sharpe/drawdown,
   trade outcomes scatter (conviction vs return).

5. Opportunity Pipeline — UOV scores table, opportunity queue, UOV
   evolution heatmap per ticker over last N cycles.

6. Order Management — stop-loss levels, trailing stop visualisation,
   adjustment history timeline.

7. Costs — daily/monthly cost charts by provider, degradation history,
   API usage stats.

Use Recharts for charts, TanStack Table for data tables. Implement
loading states, error handling, responsive sidebar navigation.

Connect to FastAPI backend. Serve via Vite in dev, FastAPI static
files in production.

Update Claude.md and README.md.
```

### Prompt 3: Deployment

Setup deployment for the dashboard on the existing Hetzner VPS:

1. Create a docker-compose.yml that runs:
   - The FastAPI dashboard backend on port 8000
   - The Vite frontend build served by FastAPI

2. Configure nginx as a reverse proxy:
   - /api/* → FastAPI backend
   - /* → React frontend static files
   - /events/stream → SSE with proper proxy buffering disabled

3. Add basic auth or API key protection

4. Create a deploy.sh script that builds the frontend, copies to the backend static dir, and restarts services

5. Ensure the dashboard database file is in a persistent location with backup considerations (reuse agent SQLite path)

Update Claude.md and README.md with deployment instructions. Ensure the dashboard reads from the same SQLite file as the agent (symlink or shared path in Docker volume).

---

## Feature Roadmap

### Phase 1 — Core Dashboard (MVP)

- **Activity Feed**: Live log of all scheduled and manual run events (cycle start/end, stocks scanned, decisions made, orders placed)
- **Stock Universe View**: Table showing current universe with labels, sector, last review date, committee verdict, and signal summary
- **Run History**: Timeline/calendar view of all past runs with drill-down into each run's decisions
- **Portfolio Snapshot**: Current holdings, P&L, allocation by sector

**Status:** ✅ Complete

### Phase 2 — Analytics & Insights

- **Decision Explorer**: For each stock, show the full committee reasoning (Claude strategy, GPT-4o skeptic, Gemini risk score) across time
- **Performance Attribution**: Which committee member's signals led to best/worst trades
- **Sector Heatmap**: Visual sector performance overlay with your holdings highlighted
- **News & Sentiment Timeline**: Market news events mapped against your trading decisions

**Status:** ✅ Complete (Phase 1.5 Analytics Lite delivered)

### Phase 3 — ML & Advanced Features

- **Prediction Confidence Dashboard**: Display model confidence scores per stock, track prediction accuracy over time
- **Backtesting Module**: Run historical simulations with different committee configurations
- **Anomaly Detection**: Flag unusual portfolio risk concentrations or abnormal price movements
- **Custom Alerts Builder**: User-defined alert rules (e.g. "notify me if any position drops 5% intraday")

**Status:** 🔄 Backlog

### Phase 4 — Interactive Control

- **Manual Override Panel**: Trigger a manual review cycle from the dashboard
- **Strategy Tuning**: Adjust committee weights, risk thresholds, and sector preferences via UI
- **Slack Integration Mirror**: See Slack conversation history with the agent, send commands from dashboard

**Status:** 🔄 Backlog (overlaps with US-1.6)

### Phase D — Research Activity (Agentic Research, US-4.4)

When [Agentic Research](AGENTIC_RESEARCH.md) is implemented: **Research Activity** panel showing per-cycle research summary (searches, cache hit rate, cost), per-ticker research trail, and research influence tracking. See `docs/AGENTIC_RESEARCH.md`.

**Status:** ⏳ Awaiting Agentic Research Phases A-C

---

## Known Issues and Fixes

All items listed here are **DONE** as of 2026-03-10.

### Test Failures (Dashboard Table Initialisation)

**Root cause:** Dashboard tables (`events_log`, `runs`) live in `dashboard.backend.app.database.Base` (separate from `src.data.models.Base`). The orchestrator/scheduler now insert into these tables via `log_event()`, but test fixtures only create agent tables → `OperationalError: no such table: events_log`.

**Failing tests fixed:**

| File | Test | Status |
|------|------|--------|
| `tests/test_notifications_integration.py` | `test_orchestrator_paused_emits_cycle_summary` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_orchestrator_emits_instruction_and_summary` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_execute_trade_emits_execution_notification` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_scheduler_exception_emits_critical` | ✅ FIXED |
| `tests/test_execution.py` | `test_get_position_returns_empty_dict_on_404` | ✅ FIXED |

**Fix pattern:**

```python
try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", ...)
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

### Frontend-Backend Type Mismatches

**Fixed:** PortfolioSnapshot, Position, Order, and Run schemas updated to match actual backend Pydantic models.

| Schema | Changes |
|--------|---------|
| PortfolioSnapshot | Renamed `snapshot_date` → `timestamp`, `total_value` → `total_value_gbp`, `cash_balance` → `cash_gbp`, `positions_json` → `positions` (array), added `invested_gbp`, `pnl_gbp`, `pnl_pct`, `num_positions` |
| Position | Renamed `value` → `value_gbp`, `pnl` → `pnl_gbp`, added `sector` |
| Order | Added `timestamp`, `order_type`, `value_gbp`, `strategy`, `conviction` |
| Run | Added `dry_run` to allowed `run_type` values |

**Status:** ✅ All frontend types aligned; `npm run build` passes without TypeScript errors

### API Client URL Mismatches

**Fixed:**
- `/api/portfolio/` endpoint corrected (was `/api/portfolio/current`)
- `getByCycleId` endpoint URL corrected

**Status:** ✅ All API routes verified

### POST /api/runs/trigger Implementation

**Implemented:** Background daemon thread that runs `Orchestrator(dry_run=True).run_cycle()`. Returns `{"message": "Dry-run cycle triggered in background", "status": "started"}`.

**POST /api/runs/trigger-live:** Same pattern but `Orchestrator(dry_run=False)` — executes real trades. Dashboard Home has Dry Run and Live Run buttons; Live Run shows a confirmation dialog.

**Status:** ✅ Endpoints functional and tested

### Verification Results

- `poetry run pytest -v` — all 207 tests pass ✅
- `cd dashboard/frontend && npm run build` — no TypeScript errors ✅
- `poetry run python -m src.orchestrator.main --dry-run` — produces stocks ✅
- Dashboard backend starts and endpoints return correct shapes ✅

---

## Design Notes

### Why Server-Sent Events (SSE) over WebSockets

The data flow is primarily server → client (push updates). SSE is simpler, works over HTTP/2, and plays nicely with nginx. WebSockets can be added later if two-way communication is needed.

### Why SQLite First

The VPS has 4GB RAM. SQLite is zero-overhead and perfectly adequate for single-user dashboard reads + agent writes. Upgrade path to Postgres when/if needed for concurrent writes or advanced queries.

### ML Extensibility

The `metadata_json` fields on events and any new tables are intentional — they allow storing arbitrary model outputs, feature vectors, or prediction scores without schema changes. This makes the dashboard future-proof for Phase 3 (ML features) and Phase D (Agentic Research).

### Ticker Format Convention

**API and database:** Use T212 format (`SYMBOL_COUNTRY_EQ`, e.g. `AAPL_US_EQ`, `BP._UK_EQ`) everywhere in the backend and in event metadata.

**Frontend:** May display a "clean" symbol (e.g. AAPL) for readability; conversion only in the UI layer. See CLAUDE.md "Ticker Format Gotcha".

### Non-blocking Event Logging

Dashboard event logging must **never** block or slow the pipeline. Use async or a background thread/queue; on failure, log and drop. Config flags `dashboard_enabled` and `dashboard_events_enabled` allow turning off event emission without code changes.

---

## Related Notes

- **CLAUDE.md** — Architecture rules, database models, configuration
- **README.md** — Quick commands including dashboard deployment
- **docs/DASHBOARD_DEPLOYMENT.md** — Deployment checklist, Docker setup, VPS access
- **docs/ARCHITECTURE.md** — Data flow, pipeline stages, component interactions
- **docs/SOPHISTICATION_ROADMAP.md** — Feature backlog, user stories (US-1.7, US-1.8)
- **docs/GOVERNANCE.md** — Audit trail, control actions, kill switches
- **docs/AGENTIC_RESEARCH.md** — Research activity (Phase D dashboard) and implementation details
