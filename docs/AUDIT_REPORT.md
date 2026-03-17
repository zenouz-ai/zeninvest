# Investment Agent — Comprehensive Audit Report

**Date:** 2026-03-17
**Scope:** Full codebase audit — execution, orchestration, strategy, moderation, risk, market data, opportunity, notifications, dashboard, testing
**Codebase:** ~29,500 lines Python across 29 test files (324 tests after audit remediation)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Order Execution Layer](#2-order-execution-layer)
3. [Orchestrator & Cycle Flow](#3-orchestrator--cycle-flow)
4. [Strategy Engine](#4-strategy-engine)
5. [Moderation Panel](#5-moderation-panel)
6. [Risk Manager](#6-risk-manager)
7. [Market Data & Universe Screening](#7-market-data--universe-screening)
8. [Opportunity Optimizer (UOV)](#8-opportunity-optimizer-uov)
9. [Notifications & Reporting](#9-notifications--reporting)
10. [Dashboard Backend](#10-dashboard-backend)
11. [Test Suite & Coverage](#11-test-suite--coverage)
12. [Configuration Summary](#12-configuration-summary)
13. [Findings & Recommendations](#13-findings--recommendations)

---

## 1. Executive Summary

The Investment Agent is a multi-LLM autonomous trading system deployed on Trading 212 Practice. The architecture is sound: a clear 8-phase pipeline (Data → Universe Screen → Strategy → Moderation → Risk → Opportunity → Execution → Journal) with defense-in-depth at every layer.

**Strengths:**
- Well-structured codebase with clear separation of concerns
- Deterministic risk rules (no LLM in risk path) with VETO power
- Graceful degradation at every phase — no cascading failures
- Comprehensive test suite (311 tests across 29 files)
- Fail-open design for non-critical services (notifications, dashboard events)
- Cost budget enforcement with per-provider daily/monthly caps

**Areas of Concern:**
- Dashboard API has no authentication (all 20 endpoints open)
- No slippage modelling or execution timing (market orders at best available)
- Partial fills are recorded but not resubmitted
- No US holiday calendar — trades may be placed on market holidays
- Position sizing is purely Claude conviction-based (no Kelly, risk-parity, or volatility targeting)
- Orchestrator integration test coverage is thin

---

## 2. Order Execution Layer

**Files:** `src/agents/execution/order_manager.py` (754 lines), `src/agents/execution/t212_client.py` (308 lines)

### 2.1 Order Types

| Type | File | Method | Details |
|------|------|--------|---------|
| Market | t212_client.py:190-204 | `place_market_order()` | Positive qty = BUY, negative = SELL. Executed immediately |
| Stop-Loss | t212_client.py:223-238 | `place_stop_order()` | GTC validity. Price = `current × (1 + stop_loss_pct/100)` |
| Limit | t212_client.py:206-221 | `place_limit_order()` | Dip-buy only. Price = `current × (1 - offset_pct/100)`. Default offset 2% |

### 2.2 Order Status Mapping

T212 API response status is mapped in order_manager.py:427-439:
- FILLED / PARTIALLY_FILLED → `"filled"`
- NEW / CONFIRMED / UNCONFIRMED / LOCAL → `"pending"`
- REJECTED / CANCELLED → `"failed"`

**Key:** System does NOT assume filled on 200 OK.

### 2.3 Deduplication

5-minute window (order_manager.py:26, 53-74). Dedup key format: `{ticker}_{BUY|SELL}_{abs_qty:.2f}`. Checked before every trade placement. Prevents double-execution of the same order within a cycle.

### 2.4 Retry Logic

**OrderManager level** (order_manager.py:200-221): Up to 3 attempts with linear backoff (5s × attempt). Only retries transient errors: timeout, 429, rate limit, connection, 502, 503.

**T212Client level** (t212_client.py:86): Tenacity decorator — 3 attempts, exponential backoff 1-4s. Non-transient errors (404, auth) fail immediately.

### 2.5 Order Value Floor

Minimum: £500 (`min_order_value_gbp`).
- **BUY**: Must be ≥ £500, else skipped
- **REDUCE**: Must be ≥ £500, else skipped. If residual would be < £500, auto-converts to full SELL
- **SELL**: Exempt from floor — allows full exit of small positions

### 2.6 Quantity Calculation

```
raw = target_amount / price
quantity = floor(raw × 100) / 100  # Floor to 2 decimal places
```

### 2.7 Partial Fill Handling

- `sync_order_status_from_t212()` runs at cycle start to update pending orders
- Filled quantity and average price recorded
- **Unfilled portions are NOT resubmitted** — remainder is lost

### 2.8 Stop-Loss Workflow

1. Stop placed after every BUY — even if status="pending" (optimistic placement)
2. Before SELL/REDUCE: `cancel_conflicting_stops(ticker)` cancels pending stops (T212 reserves shares for stops)
3. If cancellation fails, SELL is aborted (safety)
4. After REDUCE, `place_missing_stops()` re-places stop for remaining shares
5. For `liquidate_all()` (HALTED state), stop cancellation is fail-open

---

## 3. Orchestrator & Cycle Flow

**File:** `src/orchestrator/main.py` (2200+ lines)

### 3.1 Eight-Phase Pipeline

```
Phase 1: PRE-FLIGHT — paused check, cost degradation, HALTED → liquidate_all()
Phase 2: PORTFOLIO STATE — T212 API (cash, portfolio, account summary), order sync, drawdown check
Phase 3: MARKET DATA — macro intelligence, position analysis, universe screening, Finnhub/AV (deferred for intraday), web search fallback
Phase 4: STRATEGY — 3 sub-strategies (momentum, mean_reversion, factor) → Claude synthesis → decisions
Phase 5: MODERATION → RISK → EXECUTION — per-decision: GPT-4o + Gemini consensus → 9 risk rules → execute
Phase 6: OPPORTUNITY — UOV scoring, BUY reordering/queuing, limit dip-buy, execute selected BUYs
Phase 7: STOP-LOSS MANAGEMENT — place missing stops, ATR reassessment, trailing stops
Phase 8: FINALIZE — record cycle, snapshot portfolio, update metrics, emit notifications
```

### 3.2 State Machine

| State | Trigger | Behaviour |
|-------|---------|-----------|
| ACTIVE | Default | Normal operation |
| CAUTIOUS | Drawdown ≥ 30% | Risk blocks new BUYs, max position reduced to 8% |
| HALTED | Drawdown ≥ 40% | All positions liquidated, requires manual reset |

**Practice account:** State machine relaxed — always stays ACTIVE; drawdown is logged only.

### 3.3 Error Isolation

Each phase handles its own errors independently. Failures are logged but cycle continues unless critical:

| Phase | Failure | Fallback |
|-------|---------|----------|
| Portfolio fetch | API error (live) | Raise; dry-run uses mock (£10k, 0 positions) |
| Macro data | Timeout | regime=SIDEWAYS, vix=None |
| Finnhub/AV | Timeout/rate limit | Skip; use web search fallback if enabled |
| Strategy | LLM error | finalize("strategy_error"), return |
| Moderation | LLM error | Treat as BLOCKED |
| Risk | Exception | Treat as REJECT |
| Execution | T212 error | Log "failed", continue |
| Stop-loss/Journal | Failure | Log warning, continue |

### 3.4 Scheduling

**File:** `src/scheduler/scheduler.py` (333 lines)

| Mode | Times (UTC) | Frequency |
|------|------------|-----------|
| `intraday` (current) | 08:00, 12:00, 16:00 | 3×/day, Mon-Fri |
| `standard` | 07:00, 19:00 | 2×/day, Mon-Fri |

Additional jobs: daily snapshot (21:30 UTC), weekly report (Fri 22:00), instrument refresh (Sun 12:00), batch enrichment (daily 06:00).

**Run deduplication:** Scheduler creates Run record with `cycle_id = scheduled_YYYYMMDD_HHMMSS`, orchestrator updates same record on completion. One Run per scheduled cycle.

### 3.5 Dry-Run vs Live

| Aspect | Dry-Run | Live |
|--------|---------|------|
| Portfolio | Mock fallback if T212 unavailable | Real T212 data |
| Orders | Logged as "dry_run" status | Real T212 orders placed |
| State machine | Relaxed | Active (for live accounts) |
| Notifications | Suppressed by default | Sent |
| Stop-loss | Logged only | Real T212 stop orders |

---

## 4. Strategy Engine

**Files:** `src/agents/strategy/engine.py`, `src/agents/strategy/prompts.py`, `src/agents/strategy/momentum.py`, `src/agents/strategy/mean_reversion.py`, `src/agents/strategy/factor.py`

### 4.1 Sub-Strategy Weighting

| Strategy | Weight | Approach |
|----------|--------|----------|
| Momentum | 0.35 | Price trend, RSI, MACD signals |
| Mean Reversion | 0.30 | Bollinger bands, RSI extremes, price deviation |
| Factor | 0.35 | Quality + Value + Composite scoring |

### 4.2 Claude Synthesis

- Model: `claude-sonnet-4-5-20250929`
- Receives: sub-strategy scores, OHLCV + indicators, fundamentals, macro intelligence, sector headwinds, analyst data, news sentiment, portfolio context (cash%, positions, max_position%)
- Outputs per ticker: `{action, target_allocation_pct, conviction, stop_loss_pct, expected_holding_period, reasoning}`
- Actions: BUY, SELL, HOLD, REDUCE, QUEUED
- Max candidates per cycle: 35

### 4.3 Position Sizing

Conviction-based, constrained by risk rules:
- Higher conviction → larger allocation %
- Hard caps: 15% single stock (8% in CAUTIOUS), 35% sector
- VIX > 25: max 8%; VIX > 35: max 5%
- Must maintain 10% cash floor
- Max 15 concurrent positions
- REDUCE uses tier rounding: nearest of [25%, 50%, 70%, 100%]

**No Kelly Criterion, risk-parity, or volatility targeting.**

---

## 5. Moderation Panel

**File:** `src/agents/moderation/panel.py`

### 5.1 Two-Moderator Consensus

| Moderator | Model | Role |
|-----------|-------|------|
| GPT-4o | `gpt-4o` | Skeptic — challenges strategy thesis |
| Gemini Flash | `gemini-2.5-flash` | Risk assessor — growth/risk scoring |

Both must agree for trade to proceed (consensus_threshold: 2). Each assigns a score 0-100. BLOCKED if either moderator strongly opposes.

### 5.2 Cost Degradation

Budget per-provider per-day:
- Anthropic: £1/day
- OpenAI: £0.75/day
- Google: £0.50/day
- Monthly cap: £50

Degradation path: FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED

### 5.3 Research Tool Integration

When agentic research is enabled, all three pipeline members (Strategy, GPT-4o Skeptic, Gemini Risk) have tool-use loops with: `web_search`, `news_search`, `sector_search`, `sec_search`, `macro_search`. Per-member caps: Strategy 20, Skeptic 8, Risk 7. Pipeline-wide cap: 35/cycle.

---

## 6. Risk Manager

**File:** `src/agents/risk/risk_manager.py`

### 6.1 Nine Hard Rules (Deterministic — No LLM)

| # | Rule | Threshold | Behaviour |
|---|------|-----------|-----------|
| 1 | `max_single_stock` | 15% (8% in CAUTIOUS) | RESIZE to max |
| 2 | `max_sector` | 35% | RESIZE to remaining capacity |
| 3 | `max_correlation` | 0.7 | REJECT if two positions > 0.7 correlated |
| 4 | `vix_limit` | >25 → 8%, >35 → 5% | RESIZE max position |
| 5 | `cash_floor` | 10% | REJECT if trade would breach floor |
| 6 | `min_holding_period` | 24h | REJECT REDUCE if position < 24h old |
| 7 | `daily_loss_halt` | 2% daily loss | Stop trading (optional) |
| 8 | `min_positions` | 5 | Advisory — maintain diversity |
| 9 | `position_limits` | Combined sizing check | RESIZE or REJECT |

### 6.2 VETO Power

Risk VETO is final. Any rule violation either REJECTS the trade or RESIZES the allocation. No override possible.

---

## 7. Market Data & Universe Screening

### 7.1 Data Sources

| Source | Purpose | Caching |
|--------|---------|---------|
| yfinance | OHLCV, fundamentals, indicators | MarketDataCache (4h lite, 12h fundamentals) |
| Finnhub | Analyst recommendations, insider sentiment | NewsSentimentCache (6h) |
| Alpha Vantage | Broad market sentiment, ticker news | NewsSentimentCache (4h) |
| Brave/Tavily | Web search fallback when Finnhub/AV fail | Per-query |
| Macro intelligence | VIX, sector performance, economic news | 4h cache |

### 7.2 Intraday Deferred Strategy

When `cycle_frequency: intraday`, screening uses `get_stock_analysis_lite` (yfinance only). Finnhub and Alpha Vantage are fetched only for `positions ∪ top_tickers` (active-review tickers).

### 7.3 Universe Screening

- Max candidates: 35 per cycle
- Cap tiers: 70% large / 20% mid / 10% small
- Screening cooldown: 12h (overridable)
- Two pools: **review** (investigated 24-48h ago) and **new** (never/stale), 50/50 target
- When pool exhausted: fallback by `last_screened_at ASC` (least recent first)
- Proactive seed: merge additional instruments when eligible pool < 2× max_candidates
- Tickers failing yfinance OHLCV flagged `data_available=False` — permanently excluded

### 7.4 Ticker Format

| Context | Format | Example |
|---------|--------|---------|
| T212 / database | `SYMBOL_COUNTRY_EQ` | `AAPL_US_EQ` |
| yfinance / indicators | Clean symbol | `AAPL` |

Conversion via `t212_to_yf()` — handles class A/B shares (TAP/A→TAP-A, BRK_B→BRK.B).

---

## 8. Opportunity Optimizer (UOV)

**Files:** `src/agents/opportunity/scorer.py` (460 lines), `src/agents/opportunity/optimizer.py` (348 lines)

### 8.1 UOV Score Calculation

12 weighted features, z-score normalized, with EWMA smoothing:

| Feature | Weight Key | Normalization |
|---------|-----------|---------------|
| Momentum score | `momentum` | Center at 50, scale to [-1, 1] |
| Mean reversion score | `mean_reversion` | Center at 50, scale to [-1, 1] |
| Factor composite | `factor_composite` | Center at 50, scale to [-1, 1] |
| Factor quality | `factor_quality` | Center at 50, scale to [-1, 1] |
| Factor value | `factor_value` | Center at 50, scale to [-1, 1] |
| Conviction | `conviction` | Center at 50, scale to [-1, 1] |
| Holding period | `expected_holding_period` | Heuristic: <1mo=-0.4, 1-3=0, 3-6=0.25, 6-12=0.4, >12=0.2 |
| GPT verdict | `gpt_verdict` | AGREE=1, MODIFY=0.2, DISAGREE=-1 |
| Gemini growth vs risk | `gemini_growth_vs_risk` | (growth - risk) / 10, clamped |
| Gemini confidence | `gemini_confidence` | Center at 5, scale to [-1, 1] |
| News sentiment | `news_sentiment` | Regex extraction or keyword heuristic |
| Market cap | `market_cap` | log10(cap) centered at 10.5, scaled by 2.5 |

**Stage penalties** applied after z-score: strategy_hold, strategy_queued, moderation_blocked, risk_reject, risk_resize, unrated.

### 8.2 Queue Management

- `immediate_threshold_z`: 0.3 — execute BUY immediately
- `queue_threshold_z`: 0.0 — add to queue for 2nd cycle evaluation
- `queue_ttl_cycles`: 6 — expire after 6 cycles
- Promotion: queued tickers with `queued_cycles ≥ 2` and available slot/cash are promoted
- EWMA half-life: 6 cycles

### 8.3 Swap Suggestions

Compares weakest held position's UOV EWMA against new candidates. If delta ≥ `swap_delta_z`, suggests replacing weakest with stronger candidate.

---

## 9. Notifications & Reporting

### 9.1 Notification Service

**File:** `src/agents/notifications/service.py` (390 lines)

- **Fail-open design:** All exceptions caught, logged, never propagated
- **Routing:** Configurable per event type (e.g., trade execution → Slack + Email)
- **Deduplication:** Content hash with configurable window
- **Providers:** Slack (webhook), Email (SMTP)
- **Event types:** trade_instruction_approved, trade_execution_result, cycle_run_summary, state_transition, critical_cycle_failure, order_adjustment
- Dry-run alerts suppressed by default (`include_dry_run_alerts: false`)

### 9.2 Reporting

| Component | File | Purpose |
|-----------|------|---------|
| Trade journal | `reporting/journal.py` (352 lines) | Per-trade detailed log |
| Daily report | `reporting/daily_report.py` (162 lines) | End-of-day summary |
| Weekly report | `reporting/weekly_report.py` (301 lines) | Weekly performance summary |
| Performance tracker | `reporting/performance_tracker.py` (267 lines) | Sharpe, Sortino, drawdown, win rates |
| Trade outcome tracker | `reporting/trade_outcome_tracker.py` (133 lines) | BUY→SELL P&L linkage |

---

## 10. Dashboard Backend

**File:** `dashboard/backend/app/main.py`

### 10.1 Architecture

- FastAPI with 20 routers, health check, SPA fallback
- SSE event stream for real-time updates
- All queries read from agent SQLite — no duplicate tables
- CORS configured from settings (defaults to localhost)

### 10.2 Endpoints (20 routers)

dashboard, runs, status, universe, portfolio, orders, events, decisions, moderation, risk, opportunity, outcomes, stop-loss, research, performance, costs, api-usage, system, docs

### 10.3 Security Finding

**No authentication or authorization on any endpoint.** All 20 API endpoints are publicly accessible to anyone who can reach the server. The system router includes `POST /api/runs/trigger-live` which can trigger a live trading cycle.

---

## 11. Test Suite & Coverage

### 11.1 Overview

**311 tests across 29 files.** All use in-memory SQLite (conftest.py sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1`).

### 11.2 Coverage by Subsystem

| Subsystem | Test File(s) | Tests | Coverage |
|-----------|-------------|-------|----------|
| Risk Manager | test_risk_manager.py | 43 | **Excellent** — all 9 rules |
| Research | test_research.py | 37 | **Excellent** — all tools, budget, providers |
| Execution | test_execution.py | 32 | **Good** — orders, dedup, retry, sync |
| Stop-Loss | test_stop_loss_manager.py | 25 | **Good** — ATR, trailing, placement |
| Moderation | test_moderation.py | 23 | **Good** — consensus, blocking, scores |
| Screening | test_screening_cooldown.py | 17 | **Good** — cooldown, pools, rotation |
| Strategy | test_strategy.py | 17 | **Good** — sub-strategies, synthesis |
| Cost Tracker | test_cost_tracker.py | 16 | **Good** — budgets, degradation |
| Macro Intelligence | test_macro_intelligence.py | 10 | **Good** — VIX, sector, fallbacks |
| Weekly Report | test_weekly_report.py | 9 | Adequate |
| Notifications | test_notifications_*.py (4 files) | 23 | **Good** — service, formatters, providers, integration |
| Backtesting | test_backtesting_*.py (6 files) | 22 | Adequate |
| Search API Tracker | test_search_api_tracker.py | 8 | Adequate |
| Opportunity | test_opportunity_*.py (2 files) | 5 | **Thin** — basic paths only |
| Ticker Utils | test_ticker_utils.py | 6 | Adequate |
| Daily Report | test_daily_report.py | 6 | Adequate |
| Scheduler | test_scheduler_config.py | 3 | **Thin** — config parsing only |
| Dry-Run | test_dry_run_state.py | 3 | **Thin** |
| Performance Tracker | test_performance_tracker.py | 3 | **Thin** |
| Trade Outcomes | test_trade_outcome_tracker.py | 3 | **Thin** |

### 11.3 Coverage Gaps

- **Orchestrator integration:** No end-to-end `run_cycle()` test exercising the full 8-phase pipeline
- **Opportunity optimizer:** Only 5 tests for a 800-line subsystem — queue promotion, TTL expiry, swap logic under-tested
- **State machine transitions:** No test covering ACTIVE → CAUTIOUS → HALTED progression
- **Dashboard API:** No pytest-based endpoint tests (only standalone scripts in `dashboard/backend/test_*.py`)
- **Concurrent execution:** No tests for scheduler/cycle overlap scenarios

---

## 12. Configuration Summary

### 12.1 Key Parameters (config/settings.yaml)

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `cycle_frequency` | `intraday` | 3 cycles/day |
| `account_type` | `practice` | Relaxed state machine |
| `max_positions` | 15 | Max concurrent holdings |
| `cash_floor_pct` | 10 | Min cash requirement |
| `min_order_value_gbp` | 500 | BUY/REDUCE floor |
| `max_single_stock_pct` | 15 | Max per-position (8% in CAUTIOUS) |
| `max_sector_pct` | 35 | Max per-sector |
| `default_stop_loss_pct` | -8 | Default stop distance |
| `trailing_stops.default_trail_pct` | 5.0 | Trailing stop distance |
| `opportunity.mode` | `active` | UOV optimizer live |
| `opportunity.immediate_threshold_z` | 0.3 | BUY immediately threshold |
| `opportunity.queue_ttl_cycles` | 6 | Queue expiry |
| `total_monthly_gbp` | 50.00 | LLM cost cap |
| `max_candidates` | 35 | Universe screen per cycle |

---

## 13. Findings & Recommendations

### 13.1 Critical

| # | Finding | Risk | Status | Roadmap |
|---|---------|------|--------|---------|
| C1 | **Dashboard has no authentication** | Anyone with network access can trigger live trades via `POST /api/runs/trigger-live` | **Open** — tracked as US-7.1 | US-7.1 |
| C2 | **No US holiday calendar** | Orders may be submitted on market holidays, wasting API budget | **Fixed** — `src/utils/market_holidays.py` + scheduler integration | — |

### 13.2 Important

| # | Finding | Risk | Status | Roadmap |
|---|---------|------|--------|---------|
| I1 | **Partial fills not resubmitted** | Intended position size not fully achieved | **Open** — tracked as US-7.2 | US-7.2 |
| I2 | **No slippage/market impact modelling** | Market orders execute at best available; no VWAP/TWAP | **Open** — tracked as US-7.3; pre-live prerequisite | US-7.3 |
| I3 | **Position sizing is pure LLM output** | Claude decides allocation % with no quantitative framework | **Open** — already tracked as US-3.1 (Risk-Parity Sizing) | US-3.1 |
| I4 | **Orchestrator has no integration tests** | Full pipeline regressions may go undetected | **Open** — tracked as US-7.4 | US-7.4 |
| I5 | **Opportunity optimizer under-tested** | Queue promotion, TTL expiry, swap logic have minimal coverage | **Fixed** — +7 tests (TTL, capacity, cash floor, dequeue, rejections) | US-7.4 (partial) |

### 13.3 Minor / Cosmetic

| # | Finding | Notes | Status |
|---|---------|-------|--------|
| M1 | Stop-loss placed optimistically for pending BUYs | By design; may result in orphaned stops if BUY rejected by T212 | Accepted |
| M2 | Dry-run dedup doesn't prevent live duplicate | Mitigated by scheduling — unlikely to run both within 5 min | Accepted |
| M3 | `_get_previous_ewma` makes N+1 queries | One query per ticker; could be batch query for performance | **Fixed** — batched to single query with subquery |
| M4 | Queued tickers may be analyzed twice in same cycle | Once as candidate, once as queued re-evaluation (Phase 3) | Accepted |

### 13.4 Architecture Strengths

- **Defense in depth**: 4-layer pipeline (Strategy → Moderation → Risk → Execution) with any layer able to block
- **Deterministic risk**: No LLM in risk path — hard rules with VETO
- **Fail-open non-critical**: Notifications, dashboard events, web search fallback all fail without blocking trades
- **Cost guardrails**: Per-provider daily/monthly caps with graceful degradation
- **Audit trail**: Every decision, order, notification, cost, and API call logged to SQLite

---

## 14. Remediation Summary (2026-03-17)

| Item | Action Taken |
|------|-------------|
| C2 (Holiday calendar) | `src/utils/market_holidays.py` — NYSE holidays computed from rules; scheduler skips cycles on holidays; `skip_market_holidays` config setting; 7 tests |
| I5 (Optimizer tests) | +7 tests in `test_opportunity_optimizer.py`: TTL expiry, below-queue rejection, capacity gating, no-swap-empty-portfolio, cash-floor blocking, dequeue-after-execution |
| M3 (EWMA N+1) | `_get_previous_ewma` refactored from per-ticker loop to single batch query with `GROUP BY` + subquery join |
| Roadmap | 4 new user stories (US-7.1 through US-7.4) added to `SOPHISTICATION_ROADMAP.md`; existing US-3.1 and US-3.5 cross-referenced for I3 and I1 |

**Test count after audit:** 324 tests (verified via `pytest --collect-only`; +7 holiday, +7 optimizer).

---

*Report generated by comprehensive codebase audit, 2026-03-17. Updated with remediation actions same day.*
