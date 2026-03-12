# Investment Agent — Dashboard & Visualisation System

**Status:** In Progress (Phase 1 + Phase 1.5 Analytics Lite done; US-1.8 delivered)
**Roadmap reference:** `docs/SOPHISTICATION_ROADMAP.md` (US-1.7, US-1.8)
**Stabilisation plan:** `docs/DASHBOARD_STABILISATION_PLAN.md` (done)
**Deployment plan:** `docs/DASHBOARD_VPS_DEPLOYMENT_PLAN.md`
**Last updated:** 2026-03-10

---

## Project Vision

A real-time operational dashboard for the investment agent that provides full visibility into scheduled and manual runs, stock universe management, committee decisions, portfolio performance, and trading activity. Designed to be extensible for ML features (prediction models, backtesting, anomaly detection) in future phases.

---

## Current Implementation Status (2026-03-10)

### What's built

| Component | Status | Notes |
|-----------|--------|-------|
| **FastAPI Backend** | Complete | REST for runs, status (incl. system state), universe, portfolio, orders, events; **decisions** (incl. pipeline waterfall), **moderation**, **risk**, **opportunity**, **outcomes**, **stop-loss**, **performance**, **costs**, **api-usage**, **system** (state, trigger, pause, resume); SSE stream. All read from agent SQLite; no duplicate tables. |
| **Database Models** | Complete | `events_log` + `runs` tables with Alembic migration; backend queries existing agent tables only |
| **Event Logger** | Complete | Non-blocking, fail-open, background thread + queue |
| **Agent Instrumentation** | Complete | Scheduler + orchestrator emit events throughout pipeline |
| **React Frontend** | Complete | **7 pages:** Dashboard Home (system state badge ACTIVE/CAUTIOUS/HALTED, paused), Universe, Run History, Portfolio, **Opportunity Pipeline**, **Order Management**, **Costs**. Design: dark #0d1117, neutral #58a6ff, accent #d4a017, subtle grid texture. |
| **Config** | Complete | `dashboard.enabled`, `dashboard.events_enabled` in settings.yaml |

### Stabilisation (done)

See `docs/DASHBOARD_STABILISATION_PLAN.md` — all items complete: test fixtures, type alignment, API URLs, trigger endpoint.

### Phase 1.5 Analytics Lite (done)

- Decision Explorer v1: expandable Universe rows with committee reasoning (strategy, moderation, risk) and full LLM outputs (strategy full text + raw JSON, all moderators’ reasoning, risk reasoning and rules)
- Run-to-run diff: compare positions between two runs (new, closed, size changes)
- Top-bar: next run countdown, P&L summary

### Deployment (delivered)

See `docs/DASHBOARD_VPS_DEPLOYMENT_PLAN.md` — Docker service, multi-stage frontend build, SPA fallback, port 8000. Activity feed (SSE) uses relative URL — works when accessing at `http://VPS_IP:8000`. Deploy to VPS.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              React Frontend (Vite) — 7 pages                                  │
│  ┌─────────┬─────────┬─────────┬───────────┬───────────┬─────────┬────────┐ │
│  │ Home    │ Universe│ Run Hist│ Portfolio │ Opportunity│ Order   │ Costs  │ │
│  │ (state) │         │         │           │ Pipeline  │ Mgmt    │        │ │
│  └─────────┴─────────┴─────────┴───────────┴───────────┴─────────┴────────┘ │
│         Recharts / TanStack Table / dark terminal design (#0d1117, etc.)     │
└──────────────────┬──────────────────────────────────────────────────────────┘
                    │ REST + WebSocket (SSE)
┌──────────────────┴──────────────────────────────┐
│            FastAPI Backend (Python)             │
│  ┌────────────┬──────────────┬─────────────────┐ │
│  │  REST API  │  WebSocket/  │  Background     │ │
│  │  Endpoints │  SSE Push    │  Event Logger   │ │
│  └────────────┴──────────────┴─────────────────┘ │
│                    SQLite / PostgreSQL           │
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
| Database  | SQLite (start) → Postgres| Zero config for VPS, upgrade path when needed               |
| Real-time | Server-Sent Events (SSE) | Simpler than WebSockets for one-way push updates            |
| Hosting   | Same Hetzner VPS         | Co-located with agent, nginx reverse proxy                  |

---

## Feature Roadmap

### Phase 1 — Core Dashboard (MVP)
- **Activity Feed**: Live log of all scheduled and manual run events (cycle start/end, stocks scanned, decisions made, orders placed)
- **Stock Universe View**: Table showing current universe with labels, sector, last review date, committee verdict, and signal summary
- **Run History**: Timeline/calendar view of all past runs with drill-down into each run's decisions
- **Portfolio Snapshot**: Current holdings, P&L, allocation by sector

### Phase 2 — Analytics & Insights
- **Decision Explorer**: For each stock, show the full committee reasoning (Claude strategy, GPT-4o skeptic, Gemini risk score) across time
- **Performance Attribution**: Which committee member's signals led to best/worst trades
- **Sector Heatmap**: Visual sector performance overlay with your holdings highlighted
- **News & Sentiment Timeline**: Market news events mapped against your trading decisions

### Phase 3 — ML & Advanced Features
- **Prediction Confidence Dashboard**: Display model confidence scores per stock, track prediction accuracy over time
- **Backtesting Module**: Run historical simulations with different committee configurations
- **Anomaly Detection**: Flag unusual portfolio risk concentrations or abnormal price movements
- **Custom Alerts Builder**: User-defined alert rules (e.g. "notify me if any position drops 5% intraday")

### Phase 4 — Interactive Control
- **Manual Override Panel**: Trigger a manual review cycle from the dashboard
- **Strategy Tuning**: Adjust committee weights, risk thresholds, and sector preferences via UI
- **Slack Integration Mirror**: See Slack conversation history with the agent, send commands from dashboard

### Phase D — Research Activity (Agentic Research, US-4.4)
When [Agentic Research](AGENTIC_RESEARCH_PROJECT.md) is implemented: **Research Activity** panel showing per-cycle research summary (searches, cache hit rate, cost), per-ticker research trail, and research influence tracking. See `docs/AGENTIC_RESEARCH_PROJECT.md` Phase D and `docs/AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md`.

---

## Data Model (Core Tables)

**Design note:** See [Review & alignment with existing codebase](#review--alignment-with-existing-codebase) below. Prefer reading from existing agent tables where possible; add only minimal new tables for runs and events.

| Table (conceptual) | Purpose | Implementation note |
|-------------------|---------|----------------------|
| **runs** | Run metadata (type, started_at, completed_at, status, summary) | New lightweight table or derive from `strategy_decisions.cycle_id` + timestamps |
| **run_decisions** | Per-run, per-ticker decisions + committee votes | Read from existing `strategy_decisions`, `moderation_logs`, `risk_decisions` joined by cycle_id + ticker |
| **stock_universe** | Ticker, name, sector, last reviewed, label, fundamentals | Map to existing `instruments` (+ latest strategy/moderation for "label") |
| **portfolio_positions** | Current holdings, P&L, stop_loss, trailing_stop | Derive from latest `portfolio_snapshots.positions_json` or T212 API; no new table required |
| **orders** | Order history with run_id, status, t212_order_id | Use existing `orders` table |
| **events_log** | Real-time activity stream (event_type, source, message, metadata) | **New table** — agent writes here; SSE reads from here |

Example **events_log** schema (new):

```
events_log
  id, timestamp, event_type, source, message, metadata_json
```

Example **runs** schema (optional, if not derived):

```
runs
  id, type (scheduled|manual), started_at, completed_at, status, summary_json
```

---

## Claude Code Prompts

### Prompt 1 — Backend Foundation & Data Layer

```
Read Claude.md and README.md to understand the full project structure.

We are building a dashboard/visualisation system for the investment agent. This is Phase 1 — setting up the backend API and data layer.

Create a new top-level directory `dashboard/` in the repo with the following structure:

dashboard/
  backend/
    app/
      main.py          # FastAPI app with CORS, lifespan events
      database.py      # SQLAlchemy models + SQLite setup (prefer reading from src/data where possible)
      routers/
        runs.py        # GET /runs, GET /runs/{id}, POST /runs/trigger
        universe.py    # GET /universe, GET /universe/{ticker}
        portfolio.py   # GET /portfolio, GET /portfolio/history
        orders.py      # GET /orders
        events.py      # GET /events/stream (SSE endpoint)
      schemas.py       # Pydantic response models
      services/
        event_logger.py # Service that the main agent can call to log events
    requirements.txt

Implement the following:
1. SQLAlchemy models: events_log (required); runs (optional, or derive from strategy_decisions). Read universe/portfolio/orders from existing agent DB (Instrument, PortfolioSnapshot, Order, StrategyDecision, ModerationLog, RiskDecision).
2. REST endpoints for each router with proper pagination, filtering by date range and ticker. Use T212 ticker format (SYMBOL_COUNTRY_EQ) in API and DB.
3. An SSE endpoint at /events/stream that pushes new events in real-time.
4. An event_logger service with a simple API that the existing agent modules can import and call to log events (e.g. log_event("run_started", source="scheduler", metadata={...})). Must be non-blocking and fail-open (never block the pipeline).
5. Auto-generated OpenAPI docs at /docs.
6. Config: dashboard_enabled and dashboard_events_enabled in settings.yaml with disable switch.

Use SQLite for now with a clear migration path to Postgres. Include alembic setup for dashboard schema if new tables are added.

Do NOT modify existing agent code yet — just create the dashboard backend as a standalone module that can be integrated later.

Update Claude.md and README.md with the new dashboard architecture.
```

### Prompt 2 — Instrument the Agent

```
Read Claude.md and README.md.

Now integrate the dashboard event logger into the existing agent. The goal is that every significant action in the agent pipeline emits an event to the dashboard database.

Instrument the following touchpoints:
1. Scheduler: log run_started and run_completed events with run type and duration
2. Stock screener/universe builder: log universe_updated with the list of tickers and labels assigned
3. Committee decisions: log decision_made for each stock with full committee votes and reasoning
4. Order execution: log order_placed and order_executed with T212 details
5. Notification module: log notification_sent for each Slack message

Each event must be non-blocking (async or background task) and fail-open — dashboard logging must never slow or block the agent pipeline.

Also create a migration script that backfills historical data from existing tables (strategy_decisions, orders, portfolio_snapshots) into the dashboard runs/events model where applicable.

Update Claude.md.
```

### Prompt 3 — Frontend MVP

```
Read Claude.md and README.md.

Create the React frontend for the investment agent dashboard.

dashboard/
  frontend/
    src/
      components/
      pages/
      hooks/
      api/
      App.jsx
    index.html
    vite.config.js
    tailwind.config.js
    package.json

Design direction: Dark theme, financial terminal aesthetic — think Bloomberg terminal meets modern data dashboard. Use a monospace display font for numbers and a clean sans-serif for labels. Colour palette: dark charcoal background, electric green for gains, warm red for losses, cool blue for neutral/info, muted gold accents for key metrics.

Build these pages:

1. **Dashboard Home**
   - Top bar: last run timestamp, next scheduled run countdown, portfolio total value, daily P&L
   - Activity feed (real-time via SSE): scrolling log of recent events with type icons and timestamps
   - Portfolio summary cards: top holdings, sector allocation donut chart

2. **Stock Universe**
   - Searchable, sortable table of all stocks in the universe
   - Columns: ticker (display clean symbol where helpful), name, sector, label (buy/sell/hold/watch), last reviewed, committee score
   - Click a row to expand and see full committee reasoning from the last review
   - Filter by sector, label, date range

3. **Run History**
   - Timeline view of all runs (scheduled and manual)
   - Click a run to see: stocks reviewed, decisions made, orders placed
   - Visual diff: what changed between consecutive runs

4. **Portfolio**
   - Current positions table with real-time P&L
   - Historical portfolio value chart (line chart, daily granularity)
   - Sector allocation breakdown

Use Recharts for charts, TanStack Table for data tables, and connect to the FastAPI backend. Implement proper loading states, error handling, and responsive layout. Ticker display: show clean symbol (e.g. AAPL) for readability; API continues to use T212 format (AAPL_US_EQ).

The frontend should be served by the FastAPI backend in production (static files) but support Vite dev server for development.

Update Claude.md and README.md.
```

### Prompt 4 — Deployment & Nginx Setup

```
Read Claude.md and README.md.

Set up deployment for the dashboard on the existing Hetzner VPS.

1. Create a docker-compose.yml (or systemd service files) that runs:
   - The FastAPI dashboard backend on port 8000
   - The Vite frontend build served by FastAPI (or nginx)
2. Configure nginx as a reverse proxy:
   - dashboard.yourdomain.com → FastAPI backend
   - /api/* → FastAPI
   - /* → React frontend static files
   - /events/stream → SSE with proper proxy buffering disabled
3. Add basic auth or API key protection (we'll add proper auth later)
4. Create a deploy.sh script that builds the frontend, copies to the backend static dir, and restarts services
5. Ensure the dashboard database file is in a persistent location with backup considerations (reuse agent SQLite path or dedicated path)

Update Claude.md and README.md with deployment instructions.
```

### Future Prompts (Phase 2–4, keep for later)

```
# Decision Explorer — show committee reasoning over time per stock
# Sector Heatmap — visual overlay of sector performance vs holdings
# ML Prediction Dashboard — confidence scores, accuracy tracking
# Backtesting Module — historical simulation runner with UI (align with existing backtesting engine)
# Custom Alerts Builder — user-defined notification rules
# Manual Override Panel — align with US-1.6 Slack commands; same pipeline, audit trail
# Strategy Tuning UI — expose settings.yaml knobs with validation and audit
```

---

## Notes

- **Why SSE over WebSockets**: The data flow is primarily server → client (push updates). SSE is simpler, works over HTTP/2, and plays nicely with nginx. WebSockets can be added later if two-way communication is needed.
- **Why SQLite first**: The VPS has 4GB RAM. SQLite is zero-overhead and perfectly adequate for single-user dashboard reads + agent writes. Move to Postgres when/if you need concurrent writes or advanced queries.
- **ML extensibility**: The `metadata_json` fields on events and any new tables are intentional — they allow storing arbitrary model outputs, feature vectors, or prediction scores without schema changes.

---

## Review & Alignment with Existing Codebase

This section records review decisions so the implementation stays aligned with the agent’s architecture and roadmap.

### 1. Reuse existing data, minimise new tables

- **Orders**: Use existing `orders` table. Dashboard API reads from the same SQLite DB (or shared connection). No `orders` duplicate in dashboard schema.
- **Portfolio / positions**: Derive from `portfolio_snapshots.positions_json` (latest snapshot) or from live T212 positions if the orchestrator already fetches them. No separate `portfolio_positions` table unless a clear need emerges.
- **Stock universe**: Map to existing `instruments` (ticker, name, sector, last_screened_at, etc.). Add computed “label” (buy/sell/hold/watch) and “committee score” from latest `strategy_decisions` + `moderation_logs` + `risk_decisions` in the API layer.
- **Run decisions**: No new `run_decisions` table. Join existing `strategy_decisions`, `moderation_logs`, `risk_decisions` by `cycle_id` and `ticker` to build run-level and per-ticker views.
- **Runs**: Either (a) add a lightweight `runs` table (id, type, started_at, completed_at, status, summary_json) written by the orchestrator at cycle start/end, or (b) derive run list from distinct `cycle_id` and timestamps in `strategy_decisions`. Option (a) simplifies Run History and Activity Feed.
- **Events**: Add a new **events_log** table (id, timestamp, event_type, source, message, metadata_json). This is the only mandatory new table for the dashboard; agent writes here for the Activity Feed and SSE.

### 2. Ticker format

- **API and database**: Use T212 format (`SYMBOL_COUNTRY_EQ`, e.g. `AAPL_US_EQ`, `BP._UK_EQ`) everywhere in the backend and in event metadata. See CLAUDE.md “Ticker Format Gotcha”.
- **Frontend**: May display a “clean” symbol (e.g. AAPL) for readability; conversion only in the UI layer.

### 3. Event logging: non-blocking and fail-open

- Dashboard event logging must **never** block or slow the pipeline. Use async or a background thread/queue; on failure, log and drop (same philosophy as notification fail-open in CLAUDE.md).
- Add `dashboard_events_enabled` (and optionally `dashboard_enabled`) to `config/settings.yaml` so event emission can be turned off without code changes.

### 4. Relationship to existing CLI dashboard

- The existing `--dashboard` CLI (`orchestrator.main`) returns a JSON summary (portfolio, metrics, costs, positions). The **web dashboard** is the primary visualisation surface; the CLI remains for headless use, scripting, and quick checks. No need to duplicate all web features in the CLI.

### 5. Phase 4 (Interactive Control) and roadmap overlap

- **Manual Override Panel** (trigger a cycle from the UI): Overlaps with **US-1.6 Slack Natural Language Trade Commands** (buy/sell/review from Slack). Prefer implementing US-1.6 first (single-ticker pipeline + audit); then the dashboard can “Trigger manual review” by calling the same pipeline or a dedicated manual-run entrypoint, with audit logged to the same pattern.
- **Strategy Tuning via UI**: Overlaps with editing `config/settings.yaml`. Any UI that changes weights/thresholds must write through a validated path (e.g. API that updates config and reloads) with audit and a disable switch; document in GOVERNANCE.md.

### 6. Backtesting in the dashboard (Phase 3)

- The repo already has a backtesting engine (`src/backtesting/`), walk-forward validation, and promotion reports. The “Backtesting Module” in Phase 3 should be a **UI on top of** this engine (config, run, view results), not a second backtesting implementation.

---

## Documentation maintenance

When implementing or changing the dashboard:

- Update **README.md** for new commands, URLs, and deployment steps.
- Update **CLAUDE.md** for new architecture (dashboard layout, event_logger, config keys).
- Update **docs/ARCHITECTURE.md** for data flow (agent → events_log → SSE, API reading from existing tables).
- Update **docs/GOVERNANCE.md** if the dashboard gains control actions (e.g. manual run, config tuning).
- Update **docs/DEPLOYMENT.md** and **docs/LOCAL_LIVE_RUN.md** for dashboard deployment and local run.
- Keep **docs/SOPHISTICATION_ROADMAP.md** in sync with delivered phases and new user stories.
