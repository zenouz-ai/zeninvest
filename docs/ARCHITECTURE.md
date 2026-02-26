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
|                          | STEP 5 |  | STEP 6 |                          |
|                          |EXECUTE |  |JOURNAL |                          |
|                          +--------+  +--------+                          |
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
  (news sentiment)          +-- FUNDAMENTALS (P/E, P/B, ROE, margins, D/E)
                            |     (9 fields — see docs/DATA_RATIONALE.md)
                            +-- MACRO (VIX, S&P vs 200MA, market regime)
                            |
                            v
                   +-- STRATEGY ENGINE --+
                   |   Momentum (35%)    |
                   |   Mean Rev. (30%)   |---> SQLite (strategy_decisions)
                   |   Factor (35%)      |
                   +--------+------------+
                            |
                            v
Anthropic  -------> CLAUDE SONNET SYNTHESIS
  (strategy LLM)    (Final decisions with conviction)
                            |
                            v
OpenAI ----------> GPT-4o MODERATOR ---+
  (skeptic)                            |
                                       +--> MODERATION PANEL --> SQLite
Gemini ----------> GEMINI MODERATOR ---+    (consensus logic)   (moderation_logs)
  (risk assessor)                      |
                            +----------+
                            |
                            v
                   RISK MANAGER (hard rules) --> SQLite (risk_decisions)
                   [Max stock %, sector %,
                    drawdown, VIX, cash
                    floor, correlation]
                            |
                            v
Trading 212 <----- ORDER MANAGER -----------> SQLite (orders)
  (Practice API)   [Dedup, rate limit,
                    market orders]
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
+-------------------+     +-------------------+     +------------------+

+-------------------+     +-------------------+
| portfolio_snaps   |     | system_state      |
|-------------------|     |-------------------|
| total_value_gbp   |     | state (ACTIVE/    |
| cash_gbp          |     |   CAUTIOUS/HALTED)|
| invested_gbp      |     | peak_portfolio    |
| num_positions     |     | current_drawdown  |
| positions_json    |     | paused            |
| state             |     | last_cycle_at     |
+-------------------+     +-------------------+
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
        AV[Alpha Vantage<br/>News Sentiment]
        IND[Technical Indicators<br/>RSI, MACD, BB, 50MA]
        MACRO[Macro Data<br/>VIX, S&P vs 200MA]
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
        RULES[Hard Rules<br/>8 checks, VETO power]
    end

    subgraph Execution["Execution Layer"]
        OM[Order Manager<br/>Dedup + Logging]
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

    CYCLE --> YF
    CYCLE --> FH
    CYCLE --> AV
    YF --> IND
    YF --> MACRO

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

    RULES --> OM
    OM --> T212

    OM --> DB
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

    O->>D: Fetch market data
    D->>D: yfinance: OHLCV + fundamentals
    D->>D: Macro: VIX, yields, S&P
    D-->>O: Stocks data + macro

    O->>ST: Run sub-strategies
    ST->>ST: Momentum scoring
    ST->>ST: Mean reversion scoring
    ST->>ST: Factor scoring
    ST-->>O: Sub-strategy signals

    O->>CL: Synthesize decisions
    CL-->>O: Decisions with conviction

    loop For each decision
        O->>GP: Review trade proposal
        GP-->>O: Verdict + reasoning
        O->>GE: Review trade proposal
        GE-->>O: Verdict + scores
        O->>O: Determine consensus

        alt BLOCKED
            O->>O: Skip trade
        else APPROVED or CAUTION
            O->>R: Evaluate trade
            R->>R: Check 8 risk rules
            alt REJECT
                O->>O: Skip trade
            else APPROVE or RESIZE
                O->>E: Execute market order
                E->>T: POST /equity/orders/market
                T-->>E: Order confirmation
                E-->>O: Execution result
                O->>J: Generate trade journal
            end
        end
    end

    O->>O: Record cycle completion
    O->>O: Save portfolio snapshot
```

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
