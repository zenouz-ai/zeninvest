# Solution Architecture

## System Overview (ASCII)

```
+===========================================================================+
|                        INVESTMENT AGENT SYSTEM                             |
+===========================================================================+
|                                                                            |
|  +-----------------+     +------------------------------------------+     |
|  | APScheduler     |     |           ORCHESTRATOR                    |     |
|  |                 |---->|  State Machine: ACTIVE/CAUTIOUS/HALTED    |     |
|  | 07:00 UTC cycle |     |  Cycle ID tracking                       |     |
|  | 19:00 UTC cycle |     |  Error handling & recovery                |     |
|  | 21:30 snapshot  |     +----+-----------+-----------+----------+---+     |
|  | Fri 22:00 weekly|          |           |           |          |        |
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
Finnhub --------> DATA FETCHER ----+---> SQLite (market_data_cache)
  (analyst recs,   |               |
   insider sent.)  |               v
                   |        +-- INDICATORS (RSI, MACD, BB, 50MA)
Alpha Vantage --->-+        |     (8 fields — see docs/DATA_RATIONALE.md)
  (news sentiment) |        +-- FUNDAMENTALS (P/E, P/B, ROE, margins, D/E)
                   |        |     (9 fields — see docs/DATA_RATIONALE.md)
                   |        +-- MACRO (VIX, S&P vs 200MA, market regime)
                   |        |
                   |        +-- PER-TICKER NEWS (extract_per_ticker_news)
                   |        |     [Parsed from AV ticker_sentiments array,
                   |        |      per-stock sentiment scores + headlines]
                   |        |
                   |        +-- UNIVERSE SCREENER (get_screened_universe)
                   |              [Sector-balanced, cap-tiered sampling:
                   |               70% large, 20% mid, 10% small cap]
                   |              [72h screening cooldown prevents re-screening]
                   |              [Back-fills sector/market_cap to instruments]
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
  (strategy LLM)    [Sub-strategy signals + per-ticker news
                     + analyst data + portfolio state]
                     → decisions with conviction
                     → market_assessment thesis
                            |
                            v
                   MARKET CONTEXT (context.py)
                   [indicators, fundamentals,
                    macro, sub-strategy signals,
                    analyst data, per-ticker news,
                    strategy_assessment (challenge this)]
                            |
                            v
OpenAI ----------> GPT-4o MODERATOR ---+
  (skeptic)        (full data access)  |
                                       +--> MODERATION PANEL --> SQLite
Gemini ----------> GEMINI MODERATOR ---+    (consensus logic)   (moderation_logs)
  (risk assessor)  (full data access)  |
                            +----------+
                            |
                            v
                   RISK MANAGER (hard rules) --> SQLite (risk_decisions)
                   [Max stock %, sector %,
                    drawdown, VIX, cash floor,
                    correlation, REDUCE check]
                            |
                            v
Trading 212 <----- ORDER MANAGER -----------> SQLite (orders, opportunity_queue)
  (Practice API)   [Market orders (BUY/SELL/REDUCE),
                    stop-loss orders (GTC),
                    dedup + rate limit]
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
                        | Drawdown > 5%
                        v
                   +----------+
                   | CAUTIOUS |  Reduced risk
                   | Max 8%   |  No new positions
                   | per pos. |  Only add to winners
                   +----+-----+
                        |
                        | Drawdown > 15%
                        v
                    +--------+
                    | HALTED |  Emergency stop
                    | Liquid.|  Liquidate ALL positions
                    |  ALL   |  Alert operator
                    +--------+

  Recovery: Manual intervention required to move from HALTED back to ACTIVE.
  CAUTIOUS -> ACTIVE: Automatic when drawdown recovers below 5%.
```

## Cost Degradation Chain

```
  +-----------+    Google over    +------------+    OpenAI over   +-----------+
  |   FULL    | ----------------> | NO_GEMINI  | ---------------> | NO_GPT4O  |
  | All LLMs  |                   | Skip Gemini|                  | No mods   |
  | available |                   | moderator  |                  | available |
  +-----------+                   +------------+                  +-----------+
                                                                       |
                                         Anthropic over budget         |
       +--------+                   +---------------+                  |
       | HALTED | <---------------- | NO_STRATEGY   | <----------------+
       | All    |   Monthly cap     | Skip Claude   |   Anthropic over
       | halted |   exceeded        | synthesis     |
       +--------+                   +---------------+
```

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
        S1[07:00 UTC Cycle]
        S2[19:00 UTC Cycle]
        S3[21:30 Daily Snapshot]
        S4[Fri 22:00 Weekly Report]
        S5[Sun 12:00 Instrument Refresh]
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
        MACRO[Macro Data<br/>VIX, S&P vs 200MA]
        UNIV[Universe Screener<br/>Sector-balanced, cap-tiered<br/>72h cooldown]
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
    S2 --> CYCLE
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
    D->>T: GET /equity/account/cash
    D->>T: GET /equity/portfolio
    T-->>D: Cash + positions
    D-->>O: Portfolio state

    O->>D: Fetch market data (positions + universe candidates)
    D->>D: yfinance: OHLCV + fundamentals
    D->>D: Macro: VIX, yields, S&P
    D->>D: Universe screener: sector-balanced, cap-tiered (72h cooldown)
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
            O->>O: Record to rejected_stocks (stage: strategy)
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
      "industry": "Auto Manufacturers",
      "market_cap": 850000000000,
      "description": "Tesla, Inc. designs, develops, manufactures ..."
    }
  ],
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
  "cost_summary": { ... },
  "status": "completed"
}
```

Rejected stocks are tagged by the pipeline stage that blocked them:

| Stage | Meaning | Extra fields |
|-------|---------|--------------|
| `strategy` | Claude returned HOLD | reasoning, conviction |
| `moderation` | GPT-4o + Gemini consensus BLOCKED | moderation verdict |
| `risk` | Hard rules REJECTED | triggered_rules list |
| `opportunity_queue` | Approved BUY deferred by UOV queueing/capacity | queued reason + metadata |

All rejection details are also persisted in the `strategy_decisions`, `moderation_logs`, `risk_decisions`, and `opportunity_score_snapshots` tables for long-term analysis.

### State Machine

```mermaid
stateDiagram-v2
    [*] --> ACTIVE

    ACTIVE --> CAUTIOUS: Drawdown > 5%
    CAUTIOUS --> ACTIVE: Drawdown < 5%
    CAUTIOUS --> HALTED: Drawdown > 15%
    ACTIVE --> HALTED: Drawdown > 15%

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


## Planned Near-Term Extensions

These are approved near-term projects that are intentionally documented before implementation.

### 1) Chat Interface & Real-Time Alerts (US-1.5)
- **Implemented in v1:** outbound notifications for trade instruction approvals, trade execution results, cycle run summaries, state transitions, and critical failures.
- **Implemented channels:** Slack webhook + email (SMTP), with retries/timeouts/dedup and fail-open behavior.
- **Implemented persistence:** `notification_logs` table for send-attempt audit trail.
- **Operational profile (current default):**
  - `trade_instruction_approved` -> Slack only
  - `trade_execution_result` -> Slack + Email
  - `cycle_run_summary` -> Slack only
  - `state_transition` -> Slack + Email
  - `critical_cycle_failure` -> Slack + Email
  - `include_dry_run_alerts: false`
- **Hookup path used in production rollout:**
  - Slack: Incoming Webhook URL in `.env` via `SLACK_WEBHOOK_URL`
  - Email: SendGrid SMTP via `smtp.sendgrid.net:587`, `SMTP_USER=apikey`, `SMTP_USE_TLS=true`
  - Verification: inspect `notification_logs` via in-container Python query + SendGrid Email Logs for final delivery status
- **Future:** inbound command interface (`/status`, `/pause`, `/resume`, `/force-sell`) with auth and audit logs.
- Detailed plan: `docs/CHAT_INTERFACE_PROJECT.md`.

### 2) Backtesting Engine (US-5.1)
- Implemented: `src/backtesting/` — engine, paper broker, io, metrics, deterministic policy, walk-forward runner, promotion report.
- Deterministic historical replay with next-open fill and slippage; LLM-free policy proxy.
- Walk-forward validation and benchmark comparison; scenario configs (bull/bear/sideways); promotion report (safe to deploy vs hold).
- CLI: `python -m src.backtesting.main --config backtests/default.yaml`, `--synthetic`, `--walk-forward`, `--scenario bull|bear|sideways`.
- Detailed plan: `docs/BACKTESTING_PROJECT_PLAN.md`.
