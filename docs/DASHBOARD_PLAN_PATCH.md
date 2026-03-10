# Dashboard Plan — Patch Notes (Post CLAUDE.md/README.md Review)

This document patches the original `investment-dashboard-plan.md` to align with the actual project state as documented in CLAUDE.md and README.md. It also integrates the dashboard additions from the Agentic Research project (Phase D).

---

## What's Already Built (Skip These)

The following from the original plan are **already implemented** per CLAUDE.md:

- `dashboard/backend/app/main.py` — FastAPI app with CORS, lifespan events ✅
- `dashboard/backend/app/database.py` — Dashboard models (EventsLog, Run) ✅
- `dashboard/backend/app/schemas.py` — Pydantic response models ✅
- `dashboard/backend/app/routers/` — REST endpoints (runs, universe, portfolio, orders, events/SSE) ✅
- `dashboard/backend/app/services/event_logger.py` — Non-blocking event logger ✅
- Config flags: `dashboard.enabled`, `dashboard.events_enabled` ✅
- Run server: `poetry run python dashboard/backend/run_server.py` ✅
- API docs at `/docs` ✅

**Original Prompts 1 & 2 are obsolete.** The backend foundation and agent instrumentation are done.

---

## What Needs Building: Revised Frontend Plan

### Critical Architecture Decision: Query Agent DB Directly

The original plan proposed separate dashboard tables mirroring agent data. **Don't do this.** The agent's SQLite database already contains everything the frontend needs:

| Dashboard View | Agent Table(s) to Query | Notes |
|---------------|------------------------|-------|
| Activity Feed | `events_log` | Already populated by event logger ✅ |
| Run History | `runs` + `events_log` | Run metadata + per-run events ✅ |
| Stock Universe | `instruments` | Sector, industry, market_cap, business_summary, last_screened_at, data_available |
| Committee Decisions | `strategy_decisions` + `moderation_logs` + `risk_decisions` | Full pipeline trail per ticker per cycle |
| Portfolio | `portfolio_snapshots` + `orders` | Snapshots for history, orders for current state |
| P&L / Trade Outcomes | `trade_outcomes` | Links BUY→SELL with P&L, conviction, moderator scores |
| UOV Scoring | `opportunity_score_snapshots` + `opportunity_queue` | Per-cycle UOV components, queue state |
| Order Management | `orders` + `stop_loss_adjustments` | Stop-loss audit trail, trailing stops, limit orders |
| Performance | `performance_metrics` | Sharpe, Sortino, drawdown, win rates, alpha |
| Cost Tracking | `cost_logs` | Per-provider per-call costs, degradation state |
| Notifications | `notification_logs` | Sent/failed/skipped/deduped attempts |
| API Usage | `api_logs` | External API call audit (T212, Finnhub, AV) |
| Research (Phase D) | `research_logs` | Per-member research queries, cache hits, findings |
| Backtesting | `backtests/results/` (filesystem) | Walk-forward reports, promotion results |

**Action:** Extend the existing dashboard backend routers to expose these tables via REST endpoints. The `events_log` SSE stream is already wired — the rest are standard CRUD reads.

---

## Revised Frontend Feature Set

### Page 1: Dashboard Home (Operations Hub)

**Top metrics bar:**
- System state badge: ACTIVE / CAUTIOUS / HALTED (from `system_state`)
- Last cycle timestamp + next scheduled cycle countdown
- Portfolio total value + daily P&L (from latest `portfolio_snapshots`)
- Cost burn: today's LLM spend vs daily budget (from `cost_logs`)
- Degradation level: FULL / NO_GEMINI / NO_GPT4O / etc.

**Activity feed (real-time via SSE):**
- Scrolling feed from `events_log` — run_started, universe_updated, decision_made, order_placed, order_executed, notification_sent, order_adjustment, research_completed
- Each event shows: timestamp, type icon, source, message, expandable metadata
- Filter by event type, ticker, source

**Quick actions (future, ties to command gateway):**
- Trigger manual cycle (POST /runs/trigger)
- Pause/Resume trading
- Force sell a position

### Page 2: Stock Universe Explorer

**Main table (from `instruments`):**
- Columns: ticker, name, sector, industry, market_cap tier, last_screened_at, data_available
- Colour-coded labels based on latest committee verdict (from most recent `strategy_decisions` + `risk_decisions`)
- Screening cooldown indicator (greyed out if within 72h window)

**Ticker detail panel (expand/drill-down):**
- Latest committee trail: Strategy decision → Moderation scores → Risk verdict → UOV score
- Historical decisions: timeline of all past evaluations for this ticker
- Research trail (Phase D): what each member searched, key findings
- Company profile: business summary, sector, industry (from `instruments`)

**Filters:**
- Sector, market cap tier, label (buy/sell/hold/watch/queued), date range
- "Show only queued" — tickers in `opportunity_queue`
- "Show only active positions" — cross-reference with portfolio

### Page 3: Run History & Decision Explorer

**Timeline view:**
- Calendar/timeline of all cycles (from `runs`) — scheduled vs manual, duration, status
- Visual indicator for cycles that triggered trades vs no-action cycles
- Click to expand a run

**Run detail view:**
- Stocks reviewed in this run (from `strategy_decisions` where cycle matches)
- For each stock: full pipeline waterfall:
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
- Rejected stocks: which stage blocked and why

**Run comparison:**
- Select two runs side by side
- Visual diff: which tickers changed verdict between runs and why

### Page 4: Portfolio & Performance

**Current positions (from `portfolio_snapshots` + live T212 data if available):**
- Table: ticker, quantity, avg entry, current price, unrealised P&L, stop-loss level, trailing stop status
- Sector allocation donut chart
- Position sizing vs risk limits visualisation (are any positions near the 15% cap?)

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
- Queued BUY opportunities with UOV scores, queue entry date, TTL remaining
- Swap suggestions: candidate UOV vs weakest held position UOV

**UOV score evolution (from `opportunity_score_snapshots`):**
- Per-ticker UOV components over time: raw, z-score, final, EWMA
- Heatmap: all tickers × last N cycles, coloured by UOV score
- Identify patterns: which tickers are trending up in UOV (building conviction across cycles)

### Page 6: Order Management & Stop Loss Audit

**Active orders and adjustments (from `orders` + `stop_loss_adjustments`):**
- Current stop-loss levels for all positions with distance from current price
- Trailing stop tracking: high-water mark, current trail level, visualised on a mini price chart
- Limit dip-buy orders: pending limits with entry target vs current price

**Adjustment history:**
- Table: timestamp, ticker, adjustment_type (reassess/trail/limit), old_value, new_value, reason
- Chart: stop-loss level evolution vs price for a selected position

### Page 7: Cost & API Monitoring

**LLM costs (from `cost_logs`):**
- Daily spend by provider (Anthropic, OpenAI, Google) — bar chart
- Monthly cumulative vs £50 cap — progress bar
- Degradation history: when did the system drop from FULL to NO_GEMINI, etc.
- Cost per trade: total LLM cost ÷ trades executed

**API usage (from `api_logs`):**
- Calls per provider per day (T212, Finnhub, AV, Brave Search)
- Error rates and latency percentiles
- Rate limit proximity warnings

**Research costs (Phase D, from `research_logs`):**
- Per-member research spend
- Cache hit rate over time
- Most-queried tickers and topics

### Page 8: Research Explorer (Phase D — Agentic Research)

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

## Revised Backend Endpoints Needed

The existing routers cover runs, universe, portfolio, orders, and events. These additional endpoints are needed:

```
# Committee decisions
GET /api/decisions/                     # All decisions, paginated, filterable by ticker/cycle/action
GET /api/decisions/{cycle_id}           # All decisions for a specific cycle
GET /api/decisions/ticker/{ticker}      # Decision history for a ticker

# Moderation
GET /api/moderation/{cycle_id}          # Moderation logs for a cycle
GET /api/moderation/ticker/{ticker}     # Moderation history for a ticker

# Risk
GET /api/risk/{cycle_id}               # Risk decisions for a cycle

# UOV / Opportunity
GET /api/opportunity/scores/            # Latest UOV scores, paginated
GET /api/opportunity/scores/{cycle_id}  # Scores for a specific cycle
GET /api/opportunity/queue/             # Current opportunity queue
GET /api/opportunity/history/{ticker}   # UOV score history for a ticker

# Trade outcomes
GET /api/outcomes/                      # Closed trade outcomes, paginated
GET /api/outcomes/stats                 # Aggregate stats (win rate, avg P&L, etc.)

# Stop loss / order management
GET /api/stop-loss/current              # Current stop-loss levels for all positions
GET /api/stop-loss/adjustments          # Adjustment history, paginated

# Performance
GET /api/performance/metrics            # Latest performance metrics
GET /api/performance/history            # Historical metrics for charting

# Costs
GET /api/costs/daily                    # Daily cost breakdown by provider
GET /api/costs/monthly                  # Monthly cumulative
GET /api/costs/degradation              # Degradation state history

# API usage
GET /api/api-usage/daily                # API call counts and error rates

# Research (Phase D)
GET /api/research/cycle/{cycle_id}      # Research activity for a cycle
GET /api/research/ticker/{ticker}       # Research history for a ticker
GET /api/research/stats                 # Aggregate research metrics

# System
GET /api/system/state                   # Current system state (ACTIVE/CAUTIOUS/HALTED)
POST /api/system/trigger-cycle          # Trigger manual cycle
POST /api/system/pause                  # Pause trading
POST /api/system/resume                 # Resume trading
```

---

## Revised Claude Code Prompts

### Prompt 1: Extend Backend (replaces original Prompts 1-2)

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

### Prompt 2: Frontend MVP (replaces original Prompt 3)

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

### Prompt 3: Deployment (same as original Prompt 4, minor updates)

Same as original — nginx reverse proxy, basic auth, deploy.sh script. Add: ensure the dashboard reads from the same SQLite file as the agent (symlink or shared path in Docker volume).

### Prompt 4: Research Dashboard (from Agentic Research Phase D)

Only needed after Agentic Research Phases A-C are complete. Adds Page 8 (Research Explorer) and the `/api/research/` endpoints.

---

## Summary: What Goes Where

| Document | Purpose | Status |
|----------|---------|--------|
| `investment-dashboard-plan.md` | Original architecture overview (still useful for big picture) | Keep as reference, note it's superseded for prompts |
| **This file** (`DASHBOARD_PLAN_PATCH.md`) | Corrected feature set and Claude Code prompts aligned to actual codebase | **Use this for implementation** |
| `AGENTIC_RESEARCH_PROJECT.md` | Agentic research plan including dashboard Phase D | Use Phase D prompt after research is built |
| `docs/DASHBOARD_VISUALISATION_PROJECT.md` | In-repo project doc (update after implementation) | Update per mandatory docs maintenance rule |
