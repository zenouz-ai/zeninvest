# Dashboard System

> Public-safe specification for the dashboard backend, frontend, page model, and API surface.

## Purpose

The dashboard is the operator and public-observability interface for ZenInvest. It exposes pipeline state, portfolio data, opportunity ranking, run history, research traces, costs, and chat-driven workflows while maintaining a clear boundary between public-safe data and operator-only controls.

## Current Status

The dashboard is a delivered multi-page system with:

- a FastAPI backend
- a React/Vite frontend
- authenticated operator routes
- anonymous public-safe routes
- SSE activity streaming
- chat and evolution-planning surfaces

The public mirror keeps the architecture and interface design, while omitting deployment runbooks and private environment-specific hosting details.

## Architecture

### Backend

The backend reads the core SQLite persistence layer and exposes grouped APIs for:

- runs and activity
- system status and state machine data
- universe and ticker drill-down
- portfolio, orders, outcomes, and stop-loss state
- moderation and risk review
- opportunity queue and scores
- performance, costs, and API usage
- research logs and summaries
- chat/session workflows
- evolution-planning workflows
- public documentation and public-safe monitoring routes

### Frontend

The frontend is a single-page app that consumes those APIs and renders both:

- authenticated operator experiences
- sanitized anonymous views

It uses a shared design system, responsive layouts, table-heavy exploratory views, and real-time updates for operational awareness.

## Dashboard Areas

The main page groups are:

### 1. Dashboard Home

- overall state badge (`ACTIVE`, `CAUTIOUS`, `HALTED`)
- paused status
- key portfolio metrics
- recent activity feed
- alerts and hardening notices

### 2. Universe

- screened names
- sortable columns
- ticker drill-down
- public-safe capped/sanitized browsing

### 3. Runs

- cycle history
- run-level summaries
- dataset and pipeline health visibility

### 4. Portfolio

- current positions
- normalized performance views
- allocation and P&L context
- operator-only actions on top of read-only public-safe views

### 5. Opportunity Pipeline

- ranked opportunity queue
- score snapshots
- capacity and queue reasoning

### 6. Order Management

- current and historical orders
- stop-loss posture
- execution-quality visibility
- off-hours warning notes and partial-fill context

### 7. Research and Chat

- chat-first operator console
- session history and evidence panels
- planner-led workflow trace
- legacy command/audit compatibility surfaces

### 8. World News / Macro

- market regime context
- macro headline archive
- public-safe read-only macro views

### 9. Costs and API Usage

- model spend
- research spend
- degradation posture
- API consumption summaries

### 10. Roadmap / Architecture / Evolution

- roadmap visibility
- architecture context
- evolution planning workflows and gated change-management surfaces

## Access Model

The dashboard uses a public/private split:

- public routes live under `/api/public/*`
- operator routes require dashboard authentication
- public pages are either sanitized live projections or preview-only shells
- actions such as cycle triggers, pause/resume, execution, and operator planning remain private

This boundary is part of the product design, not just a deployment choice.

## API Surface

Representative route groups include:

- activity and runs
- universe and ticker views
- portfolio and performance
- public macro / world-news routes
- orders and stop-loss routes
- decisions, moderation, and risk
- opportunity and outcome routes
- costs and API usage
- documentation routes
- chat/session routes
- evolution-planning routes

The public mirror intentionally describes these groups at the capability level rather than reproducing every private operational endpoint detail.

## Data Model

The dashboard reads or extends:

- `runs`
- `events_log`
- `portfolio_snapshots`
- `orders`
- `strategy_decisions`
- `moderation_logs`
- `risk_decisions`
- `opportunity_score_snapshots`
- `opportunity_queue`
- `trade_outcomes`
- `stop_loss_adjustments`
- `performance_metrics`
- `cost_logs`
- `api_logs`
- `research_logs`
- chat/session tables
- evolution workflow tables

This gives the UI a durable audit trail rather than a transient view of the latest process state.

## Design System

The UI uses a branded dark visual language with:

- a strong typography hierarchy
- color tokens for positive/negative/risk signals
- glass/surface layering
- sparklines, cards, and dense tables
- mobile navigation fallbacks
- accessible focus and loading/error states

The public mirror keeps the conceptual design documentation while omitting environment-specific operational polish notes that are only relevant to private deployment.

## Local Development

### Backend

```bash
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd dashboard/frontend
npm install
npm run dev
```

### Frontend tests

```bash
cd dashboard/frontend
npm test
```

## Key Design Notes

- SSE is preferred for the activity stream because it fits the current read-heavy operator model well
- SQLite is sufficient for the default single-operator local/runtime posture
- public pages are not an afterthought; they are intentionally designed around sanitized data projections
- chat and research transparency are treated as first-class observability features

## Public vs Private

This public doc keeps:

- page map
- architecture
- API groups
- access model
- data model
- development workflow

It intentionally omits:

- private hosting details
- exact ingress/security edge configuration
- internal deployment prompts and runbooks

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
- [Local Setup](LOCAL_SETUP.md)
