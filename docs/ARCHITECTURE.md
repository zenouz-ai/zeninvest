# Solution Architecture

> Public technical architecture for the multi-LLM investment agent, including pipeline flow, state machine, data model, and dashboard integration.

## Purpose

This is the public architecture overview for ZenInvest. It explains how data moves from external sources through screening, strategy, moderation, risk, execution, journaling, and dashboard surfaces. It intentionally omits private deployment topology and operator-only infrastructure specifics.

## Repository Layout

- `src/` — agent runtime, orchestrator, scheduler, DB models, utilities, backtesting, and research-only learning code
- `dashboard/` — FastAPI routes/services plus React/Vite UI for dashboard and public-safe surfaces
- `docs/` — public-safe architecture, setup, dashboard, research, roadmap, and workflow documentation
- `config/` — default configuration and `.env` example
- `branding/` — public ZenInvest visual identity used by README/dashboard surfaces
- `tests/` — unit and integration coverage using in-memory SQLite by default
- `backtests/` — reusable configs and scenarios; generated results stay local under `backtests/results/`
- `data/`, `logs/`, `journals/`, and `backtests/results/` — generated local/runtime outputs that are intentionally not committed

## System Overview

```text
Scheduler
  -> Orchestrator
      -> Step 1: Data + enrichment
      -> Step 2: Strategy synthesis
      -> Step 3: Moderation / adversarial review
      -> Step 4: Deterministic risk rules
      -> Step 5: Opportunity ranking / queueing
      -> Step 6: Execution + stop management
      -> Step 7: Journaling, reports, dashboard data, notifications
```

## Data Flow

### External sources

- `yfinance` for OHLCV, price context, and baseline company data
- `Finnhub` for analyst recommendations, insider sentiment, and macro/news enrichment
- `Alpha Vantage` for news sentiment and sector data
- Search providers and SEC filing search for on-demand research
- Trading 212 practice/demo endpoints for broker execution and portfolio truth

### Pipeline stages

1. **Data fetcher**
   - pulls market, indicator, fundamental, macro, and enrichment inputs
   - applies ticker normalization and caching
2. **Universe screener**
   - rotates through candidate names
   - balances sector and cap-tier representation
   - honors cooldown and review rules
3. **Strategy engine**
   - combines sub-strategy signals such as momentum, mean reversion, factor inputs, and research context
   - produces thesis, conviction, and allocation suggestions
4. **Moderation panel**
   - skeptical review and independent risk framing
   - can use research tools when enabled
5. **Risk manager**
   - deterministic hard rules
   - final veto on sizing or execution
6. **Opportunity optimizer**
   - ranks approved ideas and manages queued opportunities
7. **Execution and stop management**
   - places broker orders
   - maintains stop-loss adjustments and pending-order cleanup
8. **Persistence and reporting**
   - records runs, decisions, moderation, risk, orders, costs, outcomes, and dashboard events

## State Machine

The orchestrator uses a three-state control model:

- `ACTIVE` — normal operation
- `CAUTIOUS` — reduced risk posture, tighter sizing and BUY restrictions
- `HALTED` — emergency stop and capital-protection posture

Transitions are driven by deterministic drawdown and hardening rules. Practice-mode workflows can relax some behaviors for safe testing, but the control model remains central to system design.

## Cost Degradation Chain

The system tracks model and research budgets and degrades in a controlled order rather than failing unpredictably.

Example high-level sequence:

```text
FULL
 -> one moderator unavailable
 -> both moderators unavailable
 -> strategy synthesis unavailable
 -> HALTED / no autonomous progression
```

This allows the system to keep producing bounded outputs when one provider is unavailable or over budget while still preventing unsafe execution.

Conversational and embedding spend have their own daily caps, tracked separately from the per-provider trading budgets (so chat or memory work cannot starve trading, and vice-versa) while still counting toward the global monthly ceiling.

## Dashboard and Public Surfaces

The dashboard backend reads the agent's persistence layer and exposes:

- authenticated operator APIs
- sanitized public APIs under `/api/public/*`
- real-time activity via SSE
- chat/session workflows
- roadmap and evolution-planning surfaces

The frontend presents both operator pages and public-safe projections. Public views are intentionally capped, sanitized, or preview-only where necessary.

## Key Subsystems

### Strategy and moderation

- strategy synthesis is multi-factor and model-assisted
- moderation introduces adversarial review rather than simple agreement checking
- model roles are intentionally differentiated so the committee produces tension, not duplicated opinions

### Risk and execution

- risk rules are deterministic and final
- broker execution supports market, limit, stop, and cancellation workflows
- execution metadata is persisted for later review, attribution, and audit

### Opportunity queue

- opportunities can be scored and queued across cycles
- queue state persists so high-quality setups are not lost when capital or risk posture blocks immediate execution

### Reporting and audit

- decisions, moderation, research, costs, runs, and trade outcomes are persisted
- chat/session flows have their own trace and action ledgers
- dashboard reporting is built from these persisted tables rather than ephemeral in-memory state

## Persistence Layer

Important table groups include:

- `runs`, `events_log`, `portfolio_snapshots`
- `strategy_decisions`, `moderation_logs`, `risk_decisions`
- `orders`, `stop_loss_adjustments`, `trade_outcomes`
- `opportunity_score_snapshots`, `opportunity_queue`
- `cost_logs`, `api_logs`, `research_logs`
- `chat_sessions`, `chat_turns`, `chat_actions`, `chat_research_logs`, `chat_workflow_steps`

The dashboard also stores dashboard-specific workflow tables for change-planning and operational review flows without overloading trading-session tables.

## Technology Stack

- Python + Poetry for backend/orchestrator code
- SQLite for the default local persistence model
- FastAPI for dashboard/backend APIs
- React + Vite for the frontend
- APScheduler for scheduled cycles and reports
- Pytest for automated validation
- Docker Compose for local/runtime multi-service packaging

## Public vs Private

The public mirror includes:

- architecture and code structure
- pipeline behavior
- state machine and cost-degradation concepts
- public/private API boundary in principle
- dashboard and persistence model

The public mirror intentionally omits:

- private domains and ingress configuration
- operator-only infrastructure topology
- mirror token workflows
- deployment runbooks and environment-specific production details

## Near-Term Extensions

Active and upcoming directions visible from the architecture:

- richer learning-loop calibration
- more adaptive regime-aware weighting
- continued evolution-planner branch workflows
- additional research routing sophistication
- incremental execution-quality and attribution improvements

### Agentic maturity (operability)

A set of low-cost operability slices, each tied to a measured baseline and deliberately avoiding new infrastructure. The zero-infra slices are **delivered**:

- per-phase cycle timing captured into the run record so latency work targets the real bottleneck
- prompt versioning/hashing across the whole committee (file-based templates, not a heavyweight registry)
- chat and embedding budget caps enforced as truly-separate categories (excluded from the per-provider trading budgets, still counted toward the monthly cap)
- a durable SQLite research cache replacing the in-memory one that reset on restart (cross-cycle, restart-safe)
- parallel moderation — the two moderators run concurrently, preserving the consensus/degradation logic, behind a kill switch
- a failure-mode catalog with stable error codes, plus golden prompt/tool tests in CI

The learning, evaluation, and memory surfaces remain strictly shadow/research-only and do not influence live orders; promotion to any live influence is gated by evidence thresholds and explicit operator sign-off.

### Track B — institutional memory (shadow-only)

Weekly export builds a text/memory corpus (`memory_bundle.jsonl`) for **operator research** on the Learning dashboard:

| Capability | Mechanism | Neo4j required? |
|------------|-----------|-----------------|
| Full live audit | SQLite tables (strategy, moderation, research, orders) | No |
| Similar-thesis search | Vector index + `/api/memory/similar` | No |
| Shadow `challenger_memory` | JSONL ticker peers | No |
| Sector + regime precedent | Optional Neo4j panel + `sync-neo4j` | Yes (optional) |
| Temporal episodes export | JSON file (`sync-graphiti`) | No |

The live committee does **not** query Neo4j or embeddings today. Docker images include the Neo4j Python driver for optional graph sync and dashboard queries.

## Related Docs

- [Local Setup](LOCAL_SETUP.md)
- [Dashboard](DASHBOARD.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md)
