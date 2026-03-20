---
tags: [architecture, pipeline, database, diagrams]
status: current
last_updated: 2026-03-17
---

# Solution Architecture

> Complete system architecture: pipeline flow, state machine, database schema, and Mermaid diagrams.

## Purpose

This document is the single source of truth for the investment agent's technical architecture. It covers the data flow from external APIs through the multi-LLM pipeline to execution, the state machine and cost degradation chain, the database schema, the dashboard backend, and the moderation consensus logic. All diagrams (ASCII and Mermaid) live here.

## System Overview (ASCII)

```
+===========================================================================+
|                        INVESTMENT AGENT SYSTEM                             |
+===========================================================================+
|                                                                            |
|  +-----------------+     +------------------------------------------+     |
|  | APScheduler     |     |           ORCHESTRATOR                    |     |
|  |                 |---->|  State Machine: ACTIVE/CAUTIOUS/HALTED    |     |
|  | 08/12/16 or 07/19 UTC cycles |     |  Cycle ID tracking                       |     |
|  | Mon-Fri, skip NYSE holidays  |     |  Error handling & recovery                |     |
|  | 21:30 snapshot  |     |                                           |     |
|  | Fri 22:00 weekly|     +----+-----------+-----------+----------+---+     |
|  | Sun 12:00 instr |          v           v           v          v        |
|  +-----------------+     +--------+  +--------+  +-------+  +--------+   |
|                          | STEP 1 |  | STEP 2 |  | STEP 3|  | STEP 4 |   |
|                          | DATA   |  |STRATEGY|  | MOD   |  | RISK   |   |
|                          +---+----+  +---+----+  +---+---+  +---+----+   |
|                              |           |           |           |        |
|                              v           v           v           v        |
|                          +--------+  +--------+  +-------+  +--------+   |
|                          | STEP 5 |  | STEP 6 |  | STEP 7 |              |
|                          |  UOV   |  |EXECUTE |  |JOURNAL |              |
|                          +--------+  +--------+  +--------+              |
|                                                                            |
+===========================================================================+
```

## Data Flow (ASCII)

```
EXTERNAL APIs                    AGENTS                         STORAGE
=============                    ======                         =======

Yahoo Finance  ----+
  (OHLCV, info)    |
                   v
Finnhub --------> DATA FETCHER ----+---> SQLite (market_data_cache, news_sentiment_cache)
  (analyst recs,   |               |     [Deferred when intraday: only for active-review tickers]
   insider sent.)  |               v
                   |        +-- INDICATORS (RSI, MACD, BB, 50MA)
Alpha Vantage --->-+        |     (8 fields — see docs/DATA_RATIONALE.md)
  (news sentiment) |        +-- FUNDAMENTALS (P/E, P/B, ROE, margins, D/E)
                   |        |     (9 fields — see docs/DATA_RATIONALE.md)
                   |        +-- MACRO (VIX, S&P vs 200MA, market regime)
                   |        +-- MACRO INTELLIGENCE (sector performance, economic headlines)
                   |        |
                   |        +-- PER-TICKER NEWS (extract_per_ticker_news)
                   |        |     [Parsed from AV ticker_sentiments array,
                   |        |      per-stock sentiment scores + headlines]
                   |        |
                   |        +-- UNIVERSE SCREENER (get_screened_universe)
                   |              [Runs every cycle regardless of state; Risk blocks new BUYs in CAUTIOUS]
                   |              [Sector-balanced, cap-tiered sampling:
                   |               70% large, 20% mid, 10% small cap]
                   |              [Cooldown: effective_screening_cooldown_override if set (e.g. 12h); else intraday=min(base, cycle_hours), standard=base; prevents re-screening within window]
                   |              [When pool exhausted: order by last_screened_at ASC to rotate; proactive seed when pool < 2×max_candidates]
                   |              [Review (24-48h ago) vs new (never or >48h) buckets, 50% each via uninvestigated_target_pct]
                   |              [Batch enrichment job (daily 06:00): cascade yfinance → Finnhub → AV OVERVIEW → BRAVE_ANSWERS for sector/market_cap/industry/business_summary; ticker conversion via ticker_utils.t212_to_yf]
                   |
                   |        +-- WEB SEARCH FALLBACK (get_news_sentiment_fallback)
                   |              [When Finnhub analyst or AV ticker sentiment fails:
                   |               Brave/Tavily supplies analyst/news snippets for strategy prompt]
                   |
                   v
          +-- STRATEGY ENGINE -----+
          |   Momentum (35%)       |
          |   Mean Rev. (30%)      |---> SQLite (strategy_decisions)
          |   Factor (35%)         |
          +--------+---------------+
                   |
                   v
Anthropic  -------> CLAUDE SONNET SYNTHESIS
  (strategy LLM)    [Sub-strategy signals + company_profiles + news_sentiment
                     (per-ticker, aggregate, broad, sector, economic) + analyst data
                     + portfolio state] → decisions with conviction
                     → market_assessment thesis
                     [When research.enabled: tool-use loop (web_search, news_search, sector_search, sec_search, macro_search) — caps 20/8/7 per member, 35 total/cycle]
                            |
                            v
                   MARKET CONTEXT (context.py)
                   [indicators, fundamentals,
                    macro (VIX, regime, sector_headwind, sector_summary, economic_highlights),
                    sub-strategy signals, analyst data, news_sentiment,
                    strategy_assessment (challenge this)]
                            |
                            v
OpenAI ----------> GPT-4o MODERATOR ---+
  (skeptic)        (full data access; when skeptic_research_enabled: tool-use)  |
                                       +--> MODERATION PANEL --> SQLite
Gemini ----------> GEMINI MODERATOR ---+    (consensus logic)   (moderation_logs)
  (risk assessor)  (full data access; when risk_research_enabled: tool-use loop)  |
                            +----------+
                            |
                            v
                   RISK MANAGER (hard rules) --> SQLite (risk_decisions)
                   [Max stock %, sector %,
                    drawdown, VIX, cash floor,
                    correlation (OHLCV returns),
                    daily loss halt (snapshot P&L),
                    REDUCE check]
                            |
                            v
Trading 212 <----- ORDER MANAGER -----------> SQLite (orders, opportunity_queue,
  (Practice API)   [Market orders (BUY/SELL/REDUCE),                stop_loss_adjustments)
                    stop-loss orders (GTC),
                    limit orders (dip-buy),
                    dedup + rate limit]
                            |
                            v
                   STOP-LOSS MANAGER ----------> SQLite (stop_loss_adjustments)
                   [ATR-based stop reassessment,
                    trailing stops (cancel+replace),
                    limit dip-buy orders]
                            ^
                            |
                   UOV SCORER + OPTIMIZER --> SQLite (opportunity_score_snapshots)
                   [Cross-cycle UOV EWMA, BUY ranking, queueing]
                   [Queue state persisted in opportunity_queue]
                            |
                            v
                   TRADE JOURNAL -----------> journals/*.md
                   [Full markdown report
                    per trade executed]
```

## State Machine

```
                    +--------+
                    | ACTIVE |  Normal operation
                    |  Full  |  Full risk budget
                    | budget |  Max 15% per position
                    +---+----+
                        |
                        | Drawdown > cautious_drawdown_pct (30%)
                        v
                   +----------+
                   | CAUTIOUS |  Reduced risk
                   | Max 8%   |  No new positions
                   | per pos. |  Only add to winners
                   +----+-----+
                        |
                        | Drawdown > halt_drawdown_pct (40%)
                        v
                    +--------+
                    | HALTED |  Emergency stop
                    | Liquid.|  Liquidate ALL positions
                    |  ALL   |  Alert operator
                    +--------+

  Recovery: Manual intervention required to move from HALTED back to ACTIVE.
  CAUTIOUS -> ACTIVE: Automatic when drawdown recovers below cautious_drawdown_pct; or `--reset-peak` / Dashboard "Reset Peak" when peak was set incorrectly.

  Practice mode: When `trading.account_type: practice`, the state machine is relaxed — drawdown is logged
  but the system always stays ACTIVE. Use `account_type: live` for real money.
```

## Cost Degradation Chain

```
  +-----------+  One moderator   +------------+  Both moderators  +-----------+
  |   FULL    | ----------------> | NO_GEMINI  | ----------------> | NO_GPT4O  |
  | All LLMs  |  over budget     | One mod     |  over budget     | No mods   |
  | available |  (Google OR      | still runs  |                  | available |
  +-----------+   OpenAI)        +------------+                   +-----------+
                                                                       |
                                         Anthropic over budget         |
       +--------+                   +---------------+                  |
       | HALTED | <---------------- | NO_STRATEGY   | <----------------+
       | All    |   Monthly cap     | Skip Claude   |   Anthropic over
       | halted |   exceeded        | synthesis     |
       +--------+                   +---------------+

  Note: Individual moderators self-check their own budgets before each call.
  NO_GEMINI is returned when Google is over budget (GPT-4o still available).
  NO_GPT4O is returned when OpenAI is over budget (Gemini still available) and
  also when both moderator budgets are exceeded.
```

## Dashboard (Phase 1 + Phase 1.5 Analytics Lite)

```
Agent pipeline (scheduler, screener, strategy, moderation, risk, execution, notifications)
    |
    v
log_event() --> events_log (non-blocking, fail-open)
    |
    v
FastAPI dashboard backend (reads agent SQLite only; no duplicate tables)
    |
    +-- GET /api/runs, /api/runs/diff, /api/status (state, paused)
    +-- GET /api/universe, /api/universe/{ticker}
    +-- GET /api/portfolio, /api/orders
    +-- GET /api/events, /api/events/stream (SSE)
    +-- POST /api/runs/trigger (dry-run), POST /api/runs/trigger-live (live cycle)
    +-- GET /api/decisions, /api/decisions/waterfall, /api/decisions/{cycle_id}, /api/decisions/ticker/{ticker}
    +-- GET /api/moderation/{cycle_id}, /api/moderation/ticker/{ticker}; GET /api/risk/{cycle_id}
    +-- GET /api/opportunity/config, /api/opportunity/scores, /api/opportunity/queue, /api/opportunity/history/{ticker}
    +-- GET /api/outcomes, /api/outcomes/stats
    +-- GET /api/research/logs, /api/research/ticker/{ticker}, /api/research/summary
    +-- GET /api/stop-loss/current, /api/stop-loss/adjustments
    +-- GET /api/performance/metrics, /api/performance/history
    +-- GET /api/costs/daily, /api/costs/monthly, /api/costs/degradation
    +-- GET /api/api-usage/daily
    +-- GET /api/system/state, POST /api/system/trigger-cycle, pause, resume
    |
    v
React frontend (SPA, served by FastAPI when dist/ exists)
    |
    +-- 8 pages: Dashboard Home (skeleton loading, alert banner, metric cards, positions with sparklines, activity feed), Universe (deep-linkable /universe/:ticker), Run History, Portfolio (sparklines, Force Sell), Opportunity Pipeline, Order Management, Costs, Roadmap & Architecture
    +-- Nav: primary 4 + "More" dropdown for secondary 4 pages
    +-- Universe: sortable columns, expandable rows with pipeline waterfall + committee reasoning, responsive column hiding
    +-- Run History: timeline, run diff (new/closed/position changes)
    +-- Portfolio: positions with inline sparklines, P&L chart, sector allocation, mobile card layout
    +-- Components: AlertBanner, Skeleton, Sparkline, PipelineWaterfall, PnlDisplay, FreshnessIndicator, useFocusTrap
```

**CORS:** Dashboard API uses configurable CORS origins via `dashboard.cors_origins` in `config/settings.yaml`. Defaults to localhost (`:3000`, `:8000`) when absent. For VPS deployment, set to the VPS IP or domain. Individual moderators self-check budgets, so the degradation level is primarily for reporting.

**Data flow:** Agent writes to `events_log` and `runs`; dashboard reads from existing agent tables (orders, portfolio_snapshots, instruments, strategy_decisions, moderation_logs, risk_decisions, opportunity_score_snapshots, opportunity_queue, trade_outcomes, stop_loss_adjustments, performance_metrics, cost_logs, api_logs, system_state). Shared SQLite DB via `./data` volume in Docker. The orchestrator **normalises T212 positions** before saving to `portfolio_snapshots.positions_json` — converting `instrument.ticker` and `walletImpact` (currentValue, unrealizedProfitLoss, totalCost) into flat fields (ticker, value_gbp, pnl_gbp, pnl_pct) for dashboard display. **Run History** displays `runs` table (one row per cycle; scheduler creates Run for scheduled cycles, passes `scheduled_cycle_id` to orchestrator which updates it—no duplicates). **Activity feed (SSE)** uses relative URL — works when accessing at `http://VPS_IP:8000`.

## Moderation Consensus Logic

```
  Strategy (always AGREE)  +  GPT-4o Verdict  +  Gemini Verdict
  ========================    ==============      ==============

  3/3 AGREE                    --> APPROVED (proceed normally)
  2/3 AGREE, 1 DISAGREE       --> CAUTION  (proceed with flag)
  2/3 DISAGREE                 --> BLOCKED  (do not trade)
  HIGH_RISK + any DISAGREE     --> BLOCKED  (do not trade)

  Fallback (1 moderator):
    AGREE + conviction >= 75   --> APPROVED
    DISAGREE                   --> BLOCKED
    else                       --> CAUTION

  Fallback (0 moderators):
    conviction >= 85           --> APPROVED
    else                       --> BLOCKED
```

## Database Schema (Key Tables)

```
+-------------------+     +-------------------+     +------------------+
| strategy_decisions|     | moderation_logs   |     | risk_decisions   |
|-------------------|     |-------------------|     |------------------|
| cycle_id          |     | cycle_id          |     | cycle_id         |
| ticker            |     | ticker            |     | ticker           |
| action            |     | moderator         |     | proposed_action  |
| conviction        |     | verdict           |     | verdict          |
| target_alloc_pct  |     | reasoning         |     | adjusted_alloc   |
| reasoning         |     | growth_score      |     | triggered_rules  |
| catalysts_json    |     | risk_score        |     | reasoning        |
| growth_potential  |     | confidence_score  |     | portfolio_state  |
| risk_level        |     | consensus         |     |                  |
| market_assessment |     |                   |     |                  |
| raw_response_json |     |                   |     |                  |
+-------------------+     +-------------------+     +------------------+
         |                         |                        |
         v                         v                        v
+-------------------+     +-------------------+     +------------------+
| orders            |     | cost_logs         |     | api_logs         |
|-------------------|     |-------------------|     |------------------|
| ticker            |     | provider          |     | service          |
| action            |     | model             |     | method           |
| quantity          |     | input_tokens      |     | endpoint         |
| price             |     | output_tokens     |     | status_code      |
| status            |     | cost_gbp          |     | duration_ms      |
| t212_order_id     |     | purpose           |     | error            |
| strategy          |     |                   |     |                  |
| conviction        |     |                   |     |                  |
+-------------------+     +-------------------+     +------------------+

+-------------------+     +-------------------+     +------------------+
| portfolio_snaps   |     | system_state      |     | instruments      |
|-------------------|     |-------------------|     |------------------|
| total_value_gbp   |     | state (ACTIVE/    |     | ticker           |
| cash_gbp          |     |   CAUTIOUS/HALTED)|     | name             |
| invested_gbp      |     | peak_portfolio    |     | sector           |
| num_positions     |     | current_drawdown  |     | industry         |
| positions_json    |     | paused            |     | market_cap       |
| state             |     | last_cycle_at     |     | business_summary |
+-------------------+     +-------------------+     | data_available   |
                                                    | last_screened_at |
                                                    +------------------+

+-------------------------+     +----------------------+
| opportunity_score_snaps |     | opportunity_queue    |
|-------------------------|     |----------------------|
| cycle_id                |     | ticker               |
| ticker                  |     | queued_cycles        |
| stage                   |     | last_uov_ewma        |
| uov_raw / z / final     |     | last_seen_cycle_id   |
| uov_ewma                |     | metadata_json        |
| moderation_consensus    |     |                      |
| risk_verdict            |     |                      |
+-------------------------+     +----------------------+
```

---

## Mermaid Diagrams

### System Architecture

```mermaid
graph TB
    subgraph Scheduler["APScheduler"]
        S1[Analysis Cycles<br/>From cycle_times_utc]
        S2[21:30 Daily Snapshot]
        S3[Fri 22:00 Weekly Report]
        S4[Sun 12:00 Instrument Refresh]
    end

    subgraph Orchestrator["Orchestrator"]
        SM[State Machine<br/>ACTIVE / CAUTIOUS / HALTED]
        CYCLE[Cycle Manager]
    end

    subgraph Data["Market Data Layer"]
        YF[yfinance<br/>OHLCV + Fundamentals]
        FH[Finnhub<br/>Analyst + Insider]
        AV[Alpha Vantage<br/>Per-Ticker News Sentiment]
        IND[Technical Indicators<br/>RSI, MACD, BB, 50MA]
        MACRO[Macro Data<br/>VIX, S&P vs 200MA<br/>+ sector perf, economic headlines]
        UNIV[Universe Screener<br/>Sector-balanced, cap-tiered<br/>configurable cooldown, effective 12h, review/new buckets]
    end

    subgraph Strategy["Strategy Engine"]
        MOM[Momentum<br/>35% weight]
        MR[Mean Reversion<br/>30% weight]
        FAC[Factor/Quality<br/>35% weight]
        CLAUDE[Claude Sonnet<br/>Final Synthesis]
    end

    subgraph Moderation["Moderation Panel"]
        GPT[GPT-4o<br/>Skeptical Analyst]
        GEM[Gemini Flash<br/>Risk Assessor]
        CONS[Consensus Logic<br/>3-way vote]
    end

    subgraph Risk["Risk Agent"]
        RULES[Hard Rules<br/>VETO power, BUY/SELL/REDUCE]
    end

    subgraph Opportunity["Opportunity Layer"]
        UOV[UOV Scorer + Optimizer<br/>Rank + Queue + Swap Suggestions]
    end

    subgraph Execution["Execution Layer"]
        OM[Order Manager<br/>Market + Stop-Loss + Dedup]
        T212[Trading 212 API<br/>Practice Mode]
    end

    subgraph Storage["Persistence"]
        DB[(SQLite<br/>WAL mode)]
        JOUR[Trade Journals<br/>Markdown files]
        LOGS[Log Files]
    end

    S1 --> CYCLE
    SM --> CYCLE

    CYCLE --> UNIV
    CYCLE --> YF
    CYCLE --> FH
    CYCLE --> AV
    YF --> IND
    YF --> MACRO
    UNIV --> YF

    IND --> MOM
    IND --> MR
    IND --> FAC
    MOM --> CLAUDE
    MR --> CLAUDE
    FAC --> CLAUDE

    CLAUDE --> GPT
    CLAUDE --> GEM
    GPT --> CONS
    GEM --> CONS

    CONS --> RULES

    RULES --> UOV
    UOV --> OM
    OM --> T212

    OM --> DB
    UOV --> DB
    OM --> JOUR
    CLAUDE --> DB
    CONS --> DB
    RULES --> DB
    CYCLE --> LOGS

    style SM fill:#f9f,stroke:#333
    style RULES fill:#f66,stroke:#333,color:#fff
    style CLAUDE fill:#66f,stroke:#333,color:#fff
    style T212 fill:#6f6,stroke:#333
```

### Pipeline Sequence

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant O as Orchestrator
    participant D as Data Fetcher
    participant ST as Strategy Engine
    participant CL as Claude Sonnet
    participant GP as GPT-4o
    participant GE as Gemini Flash
    participant R as Risk Manager
    participant U as UOV Optimizer
    participant E as Order Manager
    participant T as Trading 212
    participant J as Journal

    S->>O: Trigger cycle
    O->>O: Check state (ACTIVE/CAUTIOUS/HALTED)
    O->>O: Check cost degradation level

    O->>D: Fetch portfolio state
    D->>T: GET /equity/account/summary
    D->>T: GET /equity/account/cash
    D->>T: GET /equity/portfolio
    T-->>D: totalValue (drawdown) + cash + positions
    D-->>O: Portfolio state

    O->>E: Sync order status from T212 (pending -> filled)
    E->>T: GET /equity/history/orders
    T-->>E: Order history
    E->>E: Update Order.status for filled orders

    O->>D: Fetch market data (positions + universe candidates)
    D->>D: yfinance: OHLCV + fundamentals
    D->>D: Macro: VIX, S&P, sector performance, economic headlines
    D->>D: Universe screener: sector-balanced, cap-tiered (12h cooldown override or min(base, cycle_hours), review/new buckets)
    D->>D: Mark screened instruments (cooldown stamp)
    D->>D: Enrich instruments: back-fill sector/market_cap
    D-->>O: Stocks data + macro

    O->>ST: Run sub-strategies
    ST->>ST: Momentum scoring
    ST->>ST: Mean reversion scoring
    ST->>ST: Factor scoring
    ST-->>O: Sub-strategy signals

    O->>D: Fetch Alpha Vantage per-ticker news
    D-->>O: Per-ticker news summaries

    O->>CL: Synthesize decisions (with per-ticker news)
    CL-->>O: Decisions with conviction + market_assessment

    loop For each decision
        alt HOLD
            O->>O: Record to rejected_stocks (stage: strategy_hold or strategy_queued)
        else BUY / SELL / REDUCE
            O->>O: Build market context (per-ticker news + strategy_assessment)
            O->>GP: Review trade proposal + market context
            GP-->>O: Verdict + reasoning
            O->>GE: Review trade proposal + market context
            GE-->>O: Verdict + scores
            O->>O: Determine consensus

            alt BLOCKED
                O->>O: Record to rejected_stocks (stage: moderation)
            else APPROVED or CAUTION
                O->>R: Evaluate trade (BUY/SELL/REDUCE)
                R->>R: Check risk rules (incl. REDUCE)
                alt REJECT
                    O->>O: Record to rejected_stocks (stage: risk)
                else APPROVE or RESIZE
                    O->>U: Record evaluation for UOV (raw/z/final/ewma)
                    alt BUY
                        O->>U: Rank + queue candidates
                    else SELL / REDUCE
                        O->>E: Execute market order
                        E->>T: POST /equity/orders/market
                        T-->>E: Order confirmation
                        E-->>O: Execution result
                        O->>J: Generate trade journal
                    end
                end
            end
        end
    end

    O->>U: Select BUY execution order (active mode) or shadow-only output
    loop Selected BUYs
        O->>E: Execute ranked BUY
        E->>T: POST /equity/orders/market
        T-->>E: Order confirmation
        E-->>O: Execution result
        alt BUY with stop_loss_pct
            O->>E: Place stop-loss order (GTC)
            E->>T: POST /equity/orders/stop
            T-->>E: Stop-loss confirmation
        end
        O->>J: Generate trade journal
    end

    O->>O: Record cycle completion
    O->>O: Save portfolio snapshot
    O->>O: Return trades + rejected_stocks + opportunity_ranking + queued_candidates + swap_candidates + cost_summary
```

Execution floor guardrails:
- `min_order_value_gbp` is enforced for BUY, REDUCE, and limit BUY order paths.
- For MARKET BUYs, the floor check uses the target trade value (pre share flooring) to avoid rounding creating tiny sub-£500 logged orders.
- Explicit market SELL decisions are exempt from the floor so small positions can be fully exited.
- Protective stop-loss SELL orders are also exempt so small positions remain risk-protected.
- If a REDUCE would leave a residual position below the floor, the orchestrator converts it to full SELL before execution.
- **Market orders:** `OrderManager` calls T212 `POST /equity/orders/market` once per decision (no retry wrapper). Mutating POSTs are never auto-retried; only safe GETs use tenacity retries in `T212Client`.
- **SELL/REDUCE:** After cancelling conflicting stop orders, execution clamps share quantity to `GET /equity/portfolio/{ticker}` so a value/price-derived size cannot exceed the broker-reported position (reduces spurious 400 responses). Stop cancel failures with HTTP 404/400/409 “already gone” style bodies are treated as idempotent success.

### Cycle Output Structure

Each `run_cycle()` call returns a JSON result with:

```json
{
  "cycle_id": "cycle_20260303_0700_a1b2c3",
  "trades": [
    {
      "ticker": "AAPL_US_EQ",
      "action": "BUY",
      "allocation_pct": 8.5,
      "reasoning": "Strong momentum above 200-day MA with ...",
      "industry": "Consumer Electronics",
      "market_cap": 3200000000000,
      "description": "Apple Inc. designs, manufactures, and markets ...",
      "execution": { "status": "filled", "quantity": 12.5, "value_gbp": 850.0 },
      "moderation": "APPROVED",
      "risk": "APPROVE",
      "stop_loss": { "status": "filled", "stop_price": 168.0 }
    }
  ],
  "rejected_stocks": [
    {
      "ticker": "TSLA_US_EQ",
      "action": "BUY",
      "stage": "moderation",
      "reason": "BLOCKED by moderation consensus",
      "conviction": 72,
      "moderation_consensus": "BLOCKED",
      "industry": "Auto Manufacturers",
      "market_cap": 850000000000,
      "description": "Tesla, Inc. designs, develops, manufactures ..."
    }
  ],
  "rejected_by_action": { "BUY": 1, "HOLD": 15, "QUEUED": 9 },
  "opportunity_ranking": [
    {
      "ticker": "AAPL_US_EQ",
      "uov_raw": 0.42,
      "uov_z": 1.31,
      "uov_final": 1.31,
      "uov_ewma": 0.88,
      "is_tradable": true
    }
  ],
  "queued_candidates": [
    { "ticker": "GOOG_US_EQ", "queued_cycles": 2, "uov_ewma": 0.56 }
  ],
  "swap_candidates": [
    { "candidate_ticker": "NVDA_US_EQ", "weakest_held_ticker": "PFE_US_EQ", "delta": 1.12 }
  ],
  "num_trades": 3,
  "num_rejected": 2,
  "rejected_by_action": { "BUY": 1, "HOLD": 15, "QUEUED": 9 },
  "cost_summary": { ... },
  "status": "completed"
}
```

Rejected stocks are tagged by the pipeline stage that blocked them:

| Stage | Meaning | Extra fields |
|-------|---------|--------------|
| `strategy_hold` | Claude returned HOLD | reasoning, conviction; moderation_consensus/risk_verdict "not invoked" |
| `strategy_queued` | Claude returned QUEUED | reasoning, conviction; moderation_consensus/risk_verdict "not invoked" |
| `moderation` | GPT-4o + Gemini consensus BLOCKED | moderation verdict |
| `risk` | Hard rules REJECTED | triggered_rules list |
| `opportunity_queue` | Approved BUY deferred by UOV queueing/capacity | structured reason (awaiting_promotion, capacity_gated, below_immediate) + uov_ewma, uov_z |
| `opportunity_filtered` | Below queue threshold or dropped from queue | structured reason (below_queue, queue_expired, no_longer_eligible) + uov_ewma, uov_z |

All rejection details are also persisted in the `strategy_decisions`, `moderation_logs`, `risk_decisions`, and `opportunity_score_snapshots` tables for long-term analysis.

### State Machine

```mermaid
stateDiagram-v2
    [*] --> ACTIVE

    ACTIVE --> CAUTIOUS: Drawdown > cautious_drawdown_pct
    CAUTIOUS --> ACTIVE: Drawdown < cautious_drawdown_pct
    CAUTIOUS --> HALTED: Drawdown > halt_drawdown_pct
    ACTIVE --> HALTED: Drawdown > halt_drawdown_pct

    HALTED --> ACTIVE: Manual reset

    state ACTIVE {
        [*] --> FullBudget
        FullBudget: Full risk budget
        FullBudget: Max 15% per position
        FullBudget: All strategies active
    }

    state CAUTIOUS {
        [*] --> ReducedBudget
        ReducedBudget: Max 8% per position
        ReducedBudget: No new positions
        ReducedBudget: Only add to winners
    }

    state HALTED {
        [*] --> Emergency
        Emergency: Liquidate ALL positions
        Emergency: Stop all trading
        Emergency: Alert operator
    }
```

### Cost Degradation

```mermaid
graph LR
    A[FULL<br/>All LLMs active] -->|Google over budget| B[NO_GEMINI<br/>Skip Gemini mod]
    B -->|OpenAI over budget| C[NO_GPT4O<br/>No moderation]
    C -->|Anthropic over budget| D[NO_STRATEGY<br/>Skip Claude]
    D -->|Monthly cap hit| E[HALTED<br/>All LLM calls stop]

    style A fill:#2ecc71,color:#fff
    style B fill:#f1c40f,color:#333
    style C fill:#e67e22,color:#fff
    style D fill:#e74c3c,color:#fff
    style E fill:#8e44ad,color:#fff
```

### Technology Stack

```mermaid
graph TB
    subgraph "LLM Providers"
        A1[Anthropic<br/>Claude Sonnet 4.5]
        A2[OpenAI<br/>GPT-4o]
        A3[Google<br/>Gemini 2.5 Flash]
    end

    subgraph "Data Providers"
        D1[Yahoo Finance<br/>OHLCV + Fundamentals]
        D2[Finnhub.io<br/>Analyst + Insider]
        D3[Alpha Vantage<br/>News Sentiment]
    end

    subgraph "Execution"
        E1[Trading 212<br/>Practice API]
    end

    subgraph "Core Stack"
        P[Python 3.11]
        PO[Poetry]
        SA[SQLAlchemy + SQLite]
        AP[APScheduler]
        HX[httpx]
        TA[ta library]
    end

    subgraph "Infrastructure"
        DO[Docker + Compose]
        AL[Alembic Migrations]
        RIC[Rich Logging]
    end
```


## Near-Term Extensions

For the full prioritised backlog and detailed user story specifications, see [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md). Key delivered extensions that interact with the architecture above:

- **Chat & Notifications (US-1.5)** — Slack webhook + SMTP email alerts with fail-open behaviour and `notification_logs` audit trail. See [Chat & Commands](CHAT_AND_COMMANDS.md).
- **Backtesting Engine (US-5.1)** — daily replay engine, paper broker, walk-forward validation, promotion report. See [Backtesting](BACKTESTING.md).
- **Dashboard (US-1.7/1.8)** — FastAPI REST API + SSE stream, React frontend (8 pages). The Roadmap tab displays this architecture with roadmap-to-component mapping. See [Dashboard](DASHBOARD.md) and [Dashboard Deployment](DASHBOARD_DEPLOYMENT.md).
- **Agentic Research (US-4.4)** — *Delivered.* All three members (Strategy, GPT-4o Skeptic, Gemini Risk) have tool-use loops with 5 tools (web_search, news_search, sector_search, sec_search, macro_search). Pipeline shares a single ResearchExecutor/ResearchBudget for pipeline-wide cap enforcement. Dashboard displays per-ticker research trail: which member used which tool, queries, results, cache hits, latency, and cost. `GET /api/research/ticker/{ticker}` provides historical research per ticker. Universe table includes a `Research` column. See [Agentic Research](AGENTIC_RESEARCH.md).
- **Nemotron Integration Investigation (US-2.4)** — *Investigation only.* Candidate risk/moderation model evaluated via smoke testing and shadow-mode comparison before any promotion to live committee roles. See [Nemotron Investigation](Nemotron_3_Super_Integration_Investigation.md).

---

## Related Notes

- [Data Rationale](DATA_RATIONALE.md) — why each data point exists and how it influences decisions
- [Governance](GOVERNANCE.md) — risk rules, cost controls, audit trail
- [Deployment](DEPLOYMENT.md) — VPS setup, Docker, monitoring
- [Dashboard](DASHBOARD.md) — web dashboard design and implementation
- [Chat & Commands](CHAT_AND_COMMANDS.md) — notifications and planned inbound commands
- [Backtesting](BACKTESTING.md) — engine, walk-forward validation, promotion report
- [Agentic Research](AGENTIC_RESEARCH.md) — canonical architecture, conventions, and implementation state
- [Follow-up Routing Plan](FOLLOWUP_RESEARCH_ROUTING_PLAN.md) — routing policy (materiality + complexity gates)
- [Nemotron Investigation](Nemotron_3_Super_Integration_Investigation.md) — investigation plan, provider options, and promotion gates
