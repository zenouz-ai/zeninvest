---
tags: [roadmap, planning, user-stories, priorities]
status: current
last_updated: 2026-03-16
---

# Sophistication Roadmap

> Prioritised backlog of enhancements: user stories, acceptance criteria, and delivery status.

## Purpose

This document tracks every planned and delivered enhancement to the investment agent, ordered by priority and feasibility. It serves as the single backlog for sprint planning and as a record of what has been shipped. The dashboard **Roadmap** tab (`/roadmap`) visualises this roadmap with a timeline and architecture-to-component mapping.

---

## Roadmap overview (Delivered vs pipeline)

**At a glance:** Delivered **10** · Pipeline **18** (order by priority and feasibility below)

### Timeline view

```mermaid
timeline
    title Roadmap
    section Delivered
        US-1.1 : Performance Tracking
        US-1.2 : Trade Outcome Tracker
        US-1.3 : CLI Dashboard
        US-1.5 : Chat Interface & Alerts
        US-3.4 : UOV Ranking & Queue
        US-3.5 : Intelligent Order Management
        US-5.1 : Backtesting Engine
        US-1.8 : Dashboard VPS Deployment
        US-1.7 : Dashboard & Visualisation
        US-1.4 : Deploy POC to VPS
    section Pipeline (priority order)
        US-4.4 : Agentic Research
        US-4.5 : Proactive Macro News Intelligence
        US-1.6 : Slack NL Trade Commands
        US-1.9 : Conversational Trading Workflow
        US-2.1 : Conviction Calibration
        US-2.2 : Dynamic Strategy Weighting
        US-3.1 : Risk-Parity Sizing
        US-2.3 : Moderator Effectiveness
        US-2.4 : Nemotron Integration Investigation
        US-4.1 : Volume Signals
        US-5.2 : Parameter Sensitivity
        US-3.2 : Regime Detection
        US-3.3 : Correlation Screening
        US-4.2 : Earnings Calendar
        US-4.3 : Sector Rotation
        US-6.1 : ML Trade Scoring (investigation)
        US-6.2 : Journal Embeddings
        US-6.3 : RL Investigation
```

### Scannable roadmap (no diagram needed)

| Status | # | ID | Project |
|--------|---|-----|---------|
| **Delivered** | 1 | US-1.1 | Performance Tracking |
| | 2 | US-1.2 | Trade Outcome Tracker |
| | 3 | US-1.3 | CLI Dashboard |
| | 4 | US-1.5 | Chat Interface & Alerts |
| | 5 | US-3.4 | UOV Ranking & Queue |
| | 6 | US-3.5 | Intelligent Order Management |
| | 7 | US-5.1 | Backtesting Engine |
| | 8 | US-1.8 | Dashboard VPS Deployment |
| | 9 | US-1.7 | Dashboard & Visualisation (full API + 7 pages) |
| | 10 | US-1.4 | Deploy POC to VPS |
| **Pipeline** | 1 | US-4.4 | Agentic Research (complete: Strategy, Skeptic, and Risk tool-use loops; 5 tools; shared budget; 37 tests) |
| | 2 | US-4.5 | Proactive Macro News Intelligence |
| | 3 | US-1.6 | Slack NL Trade Commands |
| | 4 | US-1.9 | Conversational Trading Workflow |
| | 5 | US-2.1 | Conviction Calibration |
| | 6 | US-2.2 | Dynamic Strategy Weighting |
| | 7 | US-3.1 | Risk-Parity Sizing |
| | 8 | US-2.3 | Moderator Effectiveness |
| | 9 | US-2.4 | Nemotron Integration Investigation |
| | 10 | US-4.1 | Volume Signals |
| | 11 | US-5.2 | Parameter Sensitivity |
| | 12 | US-3.2 | Regime Detection |
| | 13 | US-3.3 | Correlation Screening |
| | 14 | US-4.2 | Earnings Calendar |
| | 15 | US-4.3 | Sector Rotation |
| | 16 | US-6.1 | ML Trade Scoring (investigation) |
| | 17 | US-6.2 | Journal Embeddings |
| | 18 | US-6.3 | RL Investigation |

---

## Summary: All projects

| ID | Project | Description | Benefit | Stage |
|----|---------|-------------|---------|--------|
| **US-1.1** | Performance Tracking | Daily Sharpe/Sortino/drawdown, win rate by strategy, alpha vs benchmark; `performance_metrics` table, CLI `--performance` | Enables all future improvements; can't improve what you can't measure | **Delivered** |
| **US-1.2** | Trade Outcome Tracker | Link each BUY to SELL/REDUCE; per-trade P&L, conviction linkage; `trade_outcomes` table | Core data for calibration and strategy tuning | **Delivered** |
| **US-1.3** | Performance Dashboard (CLI) | CLI `--dashboard`: portfolio value, Sharpe, win rate, costs, active positions | Immediate visibility into system behaviour | **Delivered** (export/summary open) |
| **US-1.4** | Deploy POC to VPS | Docker on VPS, health check, backup, first cycle logged | Begin gathering live market data and performance evidence | **Delivered** |
| **US-1.5** | Chat Interface & Trade Alerts | Outbound Slack + Email alerts for trades, cycle summary, state transitions, failures; `notification_logs` | Real-time operator visibility; foundation for human-in-the-loop | **Delivered** |
| **US-1.6** | Slack NL Trade Commands | Inbound Slack: BUY/SELL/REVIEW + ticker; single-ticker pipeline, user intent overwrites decision; Risk can veto | Manual override with full audit trail | **Planned** |
| **US-1.7** | Dashboard & Visualisation | Web dashboard: 7 pages (Home with state badge, Universe, Run History, Portfolio, Opportunity, Order Mgmt, Costs); full API (decisions, moderation, risk, opportunity, outcomes, stop-loss, performance, costs, api-usage, system). | Full operational visibility; personal quant experience | **Delivered** |
| **US-1.8** | Dashboard VPS Deployment | Deploy dashboard to VPS via Docker; access via VPS IP (no domain required); see `docs/DASHBOARD_DEPLOYMENT.md` | Operational visibility on live VPS | **Delivered** |
| **US-1.9** | Conversational Trading Workflow | Multi-turn, session-based Slack + dashboard chat workflow with shared session backend, explicit confirmation gate, deterministic risk veto, and full conversation/research/action audit trail; see `docs/CONVERSATIONAL_TRADING_WORKFLOW.md` | Human-in-the-loop collaborative trading with traceable decisions and safer execution control | **Planned** |
| **US-2.1** | Conviction Calibration | Calibration curve: conviction vs win rate; position sizing by calibrated confidence | Position sizing by calibrated conviction adds 2–5% annually | **Planned** |
| **US-2.2** | Dynamic Strategy Weighting | Rolling hit rate per sub-strategy; weights adjusted by performance, floor/cap | Stops allocating to strategies that aren't working | **Planned** |
| **US-2.3** | Moderator Effectiveness | Track correct blocks vs opportunity cost per moderator; monthly value-add vs cost | Informs cost optimisation; flag underperforming moderators | **Planned** |
| **US-2.4** | Nemotron Integration Investigation | Investigate NVIDIA Nemotron 3 Super as candidate risk scorer using shadow-mode evaluation, provider/cost comparison, and promotion gates | Potential cost/latency gains, provider diversification, and stronger long-context risk analysis if validated | **Planned (investigation)** |
| **US-3.1** | Risk-Parity Position Sizing | Size positions inversely to trailing volatility; equal risk contribution | Reduces volatility without reducing returns; strong academic evidence | **Planned** |
| **US-3.2** | Enhanced Regime Detection | Continuous regime score (VIX, S&P, yields); regime-aware strategy weighting | Regime-aware strategy selection improves hit rate | **Planned** |
| **US-3.3** | Correlation-Aware Screening | Flag BUY candidates with high avg correlation to portfolio | Reduces duplicate risk exposure; soft signal to committee | **Planned** |
| **US-3.4** | UOV Ranking & Queueing | Hybrid score, z-score, EWMA; ranked BUY execution; queue + swap suggestions | Solves capital saturation; deterministic opportunity ranking | **Delivered** |
| **US-3.5** | Intelligent Order Management | Stop-loss (GTC) after BUY, ATR-based stop reassessment, software trailing stops, and limit dip-buy orders | More robust downside protection and smarter entries without manual intervention | **Delivered** |
| **US-4.1** | Volume-Weighted Signals | OBV, volume SMA ratio; feed into sub-strategy scoring | Volume confirms price moves; zero-cost signal enhancement | **Planned** |
| **US-4.2** | Earnings Calendar | Next earnings date; flag "earnings imminent"; post-earnings drift signal | Avoid buying before earnings; position for post-earnings drift | **Planned** |
| **US-4.3** | Sector Rotation Signal | 11 GICS sectors via ETFs; 3-month momentum; overweight/underweight in screening | Sector momentum is real; long-term improvement | **Planned** |
| **US-4.4** | Agentic Research | 5 tools (web_search, news_search, sector_search, sec_search, macro_search) with caps 20/8/7 (total 35/cycle). All three members (Strategy, GPT-4o Skeptic, Gemini Risk) have full tool-use loops. Pipeline-wide shared budget enforcement. Brave primary, Tavily fallback. SEC EDGAR free. Latency/cost recorded. 37 unit tests. Phase 0/0.2 notebooks validated. | Stale context mitigation, follow-up ability, broader coverage | **Delivered** |
| **US-4.5** | Proactive Macro News Intelligence | Scheduled macro/geopolitical scans, second-order effect reasoning, persistent macro state, confidence-scored signals, and macro action planning with full signal-to-action audit trail; integrates with committee context and risk veto. See `docs/PROACTIVE_MACRO_NEWS_INTELLIGENCE.md`. | Portfolio-level anticipation of macro shocks/tailwinds with controlled, auditable positioning adjustments | **Planned** |
| **US-5.1** | Backtesting Engine | Replay history, paper broker, walk-forward, promotion report; yfinance + CSV cache | Release gate before strategy changes; historical confidence | **Delivered** |
| **US-5.2** | Parameter Sensitivity | Vary RSI, MA, weights, limits; heat maps; robust vs fragile ranges | Focus tuning effort on parameters that matter | **Planned** |
| **US-6.1** | Gradient-Boosted Trade Scoring | Investigation then (if justified) XGBoost on indicators + fundamentals → forward return | Potentially +3–7% annual; requires 500+ trades | **Planned** |
| **US-6.2** | Trade Journal Embeddings | Embeddings for journals; similarity search on new proposals | "Have we seen this pattern before?" context | **Planned** |
| **US-6.3** | RL Investigation | Literature + data assessment; decision gate before any implementation | Evidence-based decision on RL; document findings | **Planned** |

---

## Current state: POC (v1.0)

The POC is a fully functional autonomous trading agent running on Trading 212 Practice API with a multi-LLM pipeline. All tests pass. It is ready for VPS deployment to begin gathering live performance data.

**What the POC establishes:**
- End-to-end pipeline: Data → Screen → Strategy → Moderation → Risk → Execution → Journal → Notifications
- Multi-LLM adversarial architecture (Claude + GPT-4o + Gemini)
- Deterministic risk guardrails with VETO power
- Deterministic UOV opportunity layer (shadow/active modes, ranked BUY queue, swap suggestions)
- Cost-aware degradation; comprehensive logging and audit trail
- **Feedback loop:** performance_metrics, trade_outcomes, CLI `--performance` / `--dashboard`
- **Backtesting:** engine, paper broker, walk-forward validation, promotion report; yfinance fetch + CSV cache

**What the POC still lacks:**
- Calibration of strategy weights and conviction using live + backtest evidence
- Portfolio-level optimisation (e.g. risk-parity sizing)
- Learning/adaptation (static strategy parameters)

---

## Design principles

1. **Measure before you build** — collect live data first; only build what the data justifies  
2. **Incremental, not revolutionary** — each phase builds on the previous; no big rewrites  
3. **POC compatibility** — all enhancements integrate with the existing pipeline architecture  
4. **Evidence-based decisions** — no technique adopted without literature review and clear expected impact  
5. **Personal quant experience first** — prioritise insights, dashboards, and learning over institutional features  

---

## Priority matrix

Ordered by **priority** (P0 → P3) then **feasibility** (Easy → Medium → Hard).

| # | User Story | Value | Feasibility | Effort | Data Needed | Priority |
|---|------------|-------|-------------|--------|-------------|----------|
| 1.4 | Deploy POC to VPS | Critical | Easy | S | None | **P0** |
| 1.1 | Performance tracking | Critical | Easy | M | Existing DB | **P0** |
| 1.2 | Trade outcome tracker | Critical | Easy | M | Existing DB | **P0** |
| 1.3 | Performance dashboard (CLI) | High | Easy | S | US-1.1, 1.2 | **P1** |
| 1.5 | Chat interface + trade alerts | High | Easy–Med | M | Existing DB + events | **P1** |
| 3.1 | Risk-parity sizing | High | Easy | M | Historical prices | **P1** |
| 5.1 | Backtesting engine | High | Medium | L | yfinance history | **P1** |
| 3.5 | Intelligent order management | High | Easy–Med | M | Existing DB + T212 stops/limits | **P1** |
| 2.1 | Conviction calibration | High | Medium | M | ~50 trades | **P1** |
| 2.2 | Dynamic strategy weighting | High | Medium | M | ~50 trades | **P1** |
| 1.6 | Slack NL trade commands | High | Medium | M–L | Full pipeline | **P1** |
| 1.9 | Conversational trading workflow | High | Medium | L | US-1.6 + US-1.7 (+US-4.4 for deep research) | **P1** |
| 4.5 | Proactive macro news intelligence | High | Medium | L | Existing macro + scheduler (+US-4.4 for deeper research) | **P1** |
| 1.7 | Dashboard & Visualisation (Phase 1) | High | Medium | L | Existing DB + events_log | **P1** |
| 1.8 | Dashboard VPS Deployment | High | Easy | S | US-1.7 complete | **P1** |
| 2.3 | Moderator effectiveness | Medium | Easy | S | ~100 trades | **P2** |
| 3.3 | Correlation-aware screening | Medium | Easy | S | Historical prices | **P2** |
| 4.1 | Volume-weighted signals | Medium | Easy | S | Already fetched | **P2** |
| 4.2 | Earnings calendar | Medium | Easy | M | yfinance (free) | **P2** |
| 3.2 | Enhanced regime detection | Medium | Medium | M | Existing macro | **P2** |
| 5.2 | Parameter sensitivity | Medium | Medium | M | Backtest engine | **P2** |
| 6.1 | ML trade scoring | Medium | Hard | L | 500+ trades | **P2** |
| 4.3 | Sector rotation signal | Low–Med | Easy | M | ETF data (free) | **P3** |
| 6.2 | Journal embeddings | Low | Medium | M | Trade journals | **P3** |
| 6.3 | RL investigation | Low | Hard | M | Academic lit | **P3** |

---

## Project details (by priority)

*Phase labels (Foundation, Calibration, etc.) are thematic; execution order follows the priority matrix above.*

---

### P0 — Critical (Foundation)

**US-1.4: Deploy POC to VPS**
**Value:** Begin gathering live market data and performance evidence  
**Effort:** Small (1–2 days, following DEPLOYMENT.md)  
**Data Sources:** N/A  
**Stage:** Delivered  

**Note:** Deployment *implementation* (Docker, DEPLOYMENT.md, DASHBOARD_DEPLOYMENT.md) was delivered as code. US-1.4 is the operator checklist: run on VPS, first cycle logged, health/backup confirmed.

**Acceptance Criteria:**
- [x] Docker container running on VPS
- [x] Health check cron job active
- [x] Backup script scheduled
- [x] First successful cycle logged
- [x] Monitoring access confirmed from local machine

---

**US-1.1: Performance Tracking Module**
**Value:** Enables all future improvements — can't improve what you can't measure  
**Effort:** Medium (3–5 days)  
**Data Sources:** Existing database (portfolio_snapshots, orders, strategy_decisions)  
**Stage:** Delivered  

**Status (2026-03-05):** Delivered  

**Acceptance Criteria:**
- [x] Daily Sharpe ratio (rolling 30/60/90 day) computed from portfolio_snapshots
- [x] Sortino ratio, max drawdown, Calmar ratio tracked
- [x] Win rate by strategy (momentum, mean_reversion, factor) computed from filled orders
- [x] Alpha vs S&P 500 benchmark tracked per snapshot
- [x] Stored in `performance_metrics` table with Alembic migration
- [x] CLI command: `--performance` shows current metrics summary

**Integration:** Post-cycle step in orchestrator, after portfolio snapshot.

---

**US-1.2: Trade Outcome Tracker**
**Value:** Links strategy decisions to actual P&L — core data for calibration  
**Effort:** Medium (3–5 days)  
**Data Sources:** Existing orders + portfolio data  
**Stage:** Delivered  

**Status (2026-03-05):** Delivered  

**Acceptance Criteria:**
- [x] Each BUY tracked until corresponding SELL/REDUCE
- [x] Per-trade P&L (£ and %) with holding period
- [x] Claude conviction score linked to outcome
- [ ] Moderator verdict linked to trade outcome (optional follow-up)
- [ ] Risk decisions linked to outcomes (optional follow-up)
- [x] `trade_outcomes` table with Alembic migration

**Integration:** Updated on each SELL/REDUCE and after cycle snapshot.

---

### P1 — High (Foundation & Calibration)

**US-1.3: Performance Dashboard (CLI + Export)**
**Value:** Personal quant experience — immediate visibility  
**Effort:** Small (2–3 days)  
**Data Sources:** performance_metrics, trade_outcomes, cost_logs  
**Stage:** Delivered (CLI); export/summary open  

**Acceptance Criteria:**
- [x] `--dashboard` CLI: portfolio value, Sharpe, win rate, costs, active positions
- [ ] CSV/JSON export for Jupyter analysis
- [ ] Weekly email-style summary (journal markdown)

**Integration:** Extension of reporting module.

---

**US-1.5: Chat Interface & Real-Time Trade Alerts**
**Value:** Immediate operator visibility; foundation for human-in-the-loop  
**Effort:** Medium (4–6 days)  
**Data Sources:** Orchestrator decisions, orders, system_state, risk_decisions, moderation_logs  
**Stage:** Delivered (Phase 1 outbound)  

**Detailed plan:** `docs/CHAT_AND_COMMANDS.md`  

**Status (2026-03-05):** Delivered (Phase 1 outbound alerts)  

**Acceptance Criteria:**
- [x] Notification service under `src/agents/notifications/`
- [x] Alerts: trade_instruction_approved, trade_execution_result, cycle_run_summary, state_transition, critical_cycle_failure
- [x] Slack webhook + SMTP email; config in settings.yaml; secrets in .env.example
- [x] Retry + timeout + non-blocking; notification_logs table
- [x] VPS validation for Slack + SMTP

**Phase 2 (inbound):** Command gateway `/status`, `/pause`, `/resume`, `/force-sell`; auth; audit logging.

---

**US-3.1: Risk-Parity Position Sizing**
**Value:** High — reduces volatility without reducing returns; strong academic evidence  
**Effort:** Medium (4–5 days)  
**Data Sources:** Historical returns from market_data_cache  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Position sized inversely to trailing 60-day volatility
- [ ] Target: equal risk contribution per position
- [ ] Replaces Claude ad-hoc allocation for BUY sizing; Claude still decides what; risk-parity how much
- [ ] Existing risk limits (15% per stock, etc.) remain hard caps
- [ ] A/B log: risk-parity size vs Claude proposed size

**Technical Approach:** `weight_i = (1/vol_i) / sum(1/vol_j)`.  
**Literature:** Maillard, Roncalli & Teiletche (2010) "The Properties of Equally Weighted Risk Contribution Portfolios"

---

**US-5.1: Backtesting Engine**
**Value:** Critical for long-term confidence; release gate before strategy changes  
**Effort:** Large (5–8 days)  
**Data Sources:** yfinance historical (fetch + CSV cache when data/backtest/ empty)  
**Stage:** Delivered  

**Detailed plan:** `docs/BACKTESTING.md` (includes walk-forward validation and promotion report).  

**Status (2026-03):** Delivered  

**Acceptance Criteria:**
- [x] Replay historical data; deterministic policy (LLM-free proxy)
- [x] Paper broker; risk rules, position sizing, constraints
- [x] Output: equity curve, Sharpe, max drawdown, win rate, trades.csv, results.json
- [x] Walk-forward validation; promotion report (safe to deploy vs hold)
- [x] Compare vs buy-and-hold SPY; yfinance fetch + CSV cache

**Integration:** CLI `--config`, `--synthetic`, `--walk-forward`, `--scenario bull|bear|sideways`.

---

**US-3.5: Intelligent Order Management (Stop-Loss, Trailing, Limit Dip-Buy)**

**Value:** Automatic downside protection and smarter entries without manual intervention  
**Effort:** Medium (implemented)  
**Data Sources:** Existing orders, positions, indicators (ATR), T212 stop/limit APIs  
**Stage:** Delivered  

**Summary:**  
Implements an order-management layer that automatically:  
- Places a **GTC stop-loss after every BUY** using Claude's `stop_loss_pct`.  
- **Reassesses stops each cycle** using 14-day ATR × configurable multiplier, clamped to `[min_stop_distance_pct, max_stop_distance_pct]`, and (by default) only tightens stops (never widens).  
- Provides **software trailing stops** using a high-water mark per position and cancel+replace semantics, since T212 has no native trailing stop.  
- Supports **limit dip-buy entries** when strategy outputs `entry_type: "limit_dip"`, placing a limit BUY below current price with configurable offset and validity.  

All adjustments are persisted in `stop_loss_adjustments` and emitted as `order_adjustment` Slack notifications. Behaviour and config are documented in `docs/ORDER_MANAGEMENT_PROJECT.md` and referenced from `GOVERNANCE.md` (§3.3 Intelligent Order Management).

**Integration:**  
- `OrderManager.place_stop_loss()` called after successful BUY executions.  
- `StopLossManager.reassess_stops()` and `StopLossManager.apply_trailing_stops()` run after execution each cycle.  
- BUY path branches on `decision.entry_type` (`market` vs `limit_dip`) to choose market vs limit orders.  

---

**US-2.1: Conviction Calibration**
**Value:** Position sizing by calibrated conviction can add 2–5% annually  
**Effort:** Medium (3–4 days)  
**Data Sources:** trade_outcomes, strategy_decisions  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Calibration curve: conviction vs win rate (bins 50–60, 60–70, 70–80, 80+)
- [ ] Min 30 trades per bin before activating
- [ ] Position sizing: `size = base_size * calibration_factor`
- [ ] Logged for audit; fallback to current behaviour if insufficient data

**Technical Approach:** Empirical calibration curve or simple logistic regression; no ML.

---

**US-2.2: Dynamic Strategy Weighting**
**Value:** Stops allocating to strategies that aren't working in current regime  
**Effort:** Medium (3–4 days)  
**Data Sources:** trade_outcomes, strategy_decisions  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Rolling 30-day hit rate per sub-strategy (momentum, mean_reversion, factor)
- [ ] Weights: `new_weight = base_weight * rolling_hit_rate / avg_hit_rate`; floor 15%, cap 50%
- [ ] Weight changes logged; configurable `dynamic_weighting: true/false`

**Technical Approach:** EWMA of success rate; transparent, no ML.

---

**US-1.6: Slack Natural Language Trade Commands**
**Value:** Manual override with full audit trail; single-ticker pipeline; user intent overwrites decision; Risk can veto  
**Effort:** Medium–Large (5–8 days)  
**Data Sources:** Full pipeline; new `slack_command_log`  
**Stage:** Planned  

**Detailed plan:** `docs/CHAT_AND_COMMANDS.md`.  

**Acceptance Criteria:**
- [ ] Inbound Slack listener (Socket Mode)
- [ ] NL parser: BUY/SELL/REVIEW + ticker + quantity or amount (£)
- [ ] Single-ticker pipeline (cycle_id = `slack-{ts}`); final action = user intent; risk can veto
- [ ] REVIEW: run pipeline, post summary, no order
- [ ] Execute via OrderManager; Order.strategy = `slack_command`; confirm in Slack
- [ ] Safety: ticker validation, cash/position checks, large-order confirmation, risk veto messaging
- [ ] `slack_command_log`; CLI `slack_trade_listener`

**Integration:** Long-running process; reuses Strategy/Moderation/Risk/Execution stack.

---

**US-1.9: Conversational Trading Workflow**
**Value:** Multi-turn collaborative trading across Slack and dashboard with persistent context and explicit action confirmation  
**Effort:** Large (8–12 days, phased delivery)  
**Data Sources:** Existing pipeline + new chat session/turn/action tables + optional agentic research tools  
**Stage:** Planned  

**Detailed plan:** `docs/CONVERSATIONAL_TRADING_WORKFLOW.md`.

**Acceptance Criteria:**
- [ ] Session management supports start/resume/end/timeout with persistent multi-turn context
- [ ] Shared backend supports Slack thread and dashboard chat continuity
- [ ] Agent provides structured research summaries and follow-up refinements by turn
- [ ] Every trade action requires explicit confirmation; no execution on ambiguous intent
- [ ] RiskManager remains final deterministic veto with clear rejection reasons
- [ ] Full audit trail for turns, research calls, recommendations, confirmations, and executions
- [ ] Dashboard chat APIs and SSE events support real-time conversational updates

**Dependencies:**
- Requires US-1.6 for robust inbound Slack handling baseline
- Requires US-1.7 backend/frontend extension for chat panel and APIs
- Uses US-4.4 research tooling when enabled; core session + confirmation flow can ship without deep tool-use

---

**US-4.5: Proactive Macro News Intelligence**
**Value:** Portfolio-level anticipation of macro shocks/tailwinds via proactive scanning and second-order reasoning  
**Effort:** Large (8–12 days, phased delivery)  
**Data Sources:** Existing macro module + Finnhub/AV/yfinance + scheduled scans + optional Brave/Tavily/Browser research  
**Stage:** Planned  

**Detailed plan:** `docs/PROACTIVE_MACRO_NEWS_INTELLIGENCE.md`.

**Acceptance Criteria:**
- [ ] Independent macro scan schedule runs multiple times daily with persisted scan history
- [ ] Macro events are classified into taxonomy and transformed into confidence-scored signals
- [ ] Persistent macro state is maintained across scans (regime memory)
- [ ] Committee receives macro state/signals as explicit context in decision flow
- [ ] Macro action planner outputs review-first positioning recommendations with audit links
- [ ] Optional auto-actions are gated by confidence thresholds, daily swing caps, and deterministic risk veto
- [ ] Full signal-to-action audit trail exists (news -> reasoning -> signal -> recommendation -> outcome)

**Dependencies:**
- Can start now using existing macro intelligence and scheduler primitives
- Benefits from US-4.4 tooling for deeper source coverage and richer reasoning traces
- Integrates with existing RiskManager veto path; no bypass allowed

---

**US-2.4: Nemotron Integration Investigation**
**Value:** Potential moderation/risk model cost reduction, faster inference, and provider diversification if quality is maintained
**Effort:** Investigation (2-4 days for smoke + shadow setup planning)
**Data Sources:** Existing committee inputs, moderation logs, risk decisions, cost logs
**Stage:** Planned (investigation)

**Detailed plan:** `docs/Nemotron_3_Super_Integration_Investigation.md`.

**Investigation Criteria:**
- [ ] API smoke test passes for at least one provider path (OpenRouter or NVIDIA NIM)
- [ ] Shadow comparison vs Gemini risk role across minimum 5 full cycles
- [ ] No material quality regression in risk assessments
- [ ] Cost and latency profile documented against current moderator stack
- [ ] Promotion decision documented: promote, hold as optional 4th voice, or archive

---

**US-1.7: Dashboard & Visualisation System (Phase 1 MVP + full API)**
**Value:** Full operational visibility — activity feed, universe, run history, portfolio, opportunity, order management, costs
**Effort:** Large (8–12 days for backend + instrumentation + frontend + deploy)
**Data Sources:** Existing DB; new `events_log` (optionally `runs`); backend reads agent tables read-only (no duplicate tables)
**Stage:** In Progress (full API and 7 pages on branch `feature/dashboard-full-spec`)

**Detailed plan:** `docs/DASHBOARD.md`.

**Status (2026-03-10):** Backend (FastAPI + SSE + event logger) and frontend (React + Vite + Tailwind) are built. Agent instrumentation complete. Stabilisation complete. US-1.8 implemented: Docker service, multi-stage frontend build, SPA fallback. Phase 1.5 Analytics Lite: Decision Explorer (expandable universe rows), run diff, next-run countdown, P&L in top bar. **Full API and 7-page spec** (branch `feature/dashboard-full-spec`): backend exposes decisions, moderation, risk, opportunity, outcomes, stop-loss, performance, costs, api-usage, system; status includes system state (ACTIVE/CAUTIOUS/HALTED) and paused; frontend has 7 pages (Dashboard Home with state badge, Universe, Run History, Portfolio, Opportunity Pipeline, Order Management, Costs); Universe table shows `Investigated`, `Reviews`, `Decisions`, `Holding`, `Sold`, and `UOV (ewma)` per ticker, where `Sold` is computed from executed and dry-run SELL orders only. Dashboard Home includes a “Latest trades & LLM reasons” audit table that surfaces recent orders (including failed attempts) with the latest committee reasoning by ticker; design tokens #0d1117, #58a6ff, #d4a017, grid texture.

**Phase 1 Acceptance Criteria:**
- [x] FastAPI backend: REST runs/universe/portfolio/orders; SSE `/events/stream`
- [x] Read from existing tables; add only events_log + runs
- [x] Event logger: non-blocking, fail-open; instrument scheduler, screener, committee, execution, notifications
- [x] React + Vite + Tailwind: Home (activity feed, portfolio summary), Universe (table, committee reasoning), Run History (timeline), Portfolio (positions, P&L chart)
- [x] Dark terminal aesthetic; Recharts; config `dashboard_enabled`, `dashboard_events_enabled`
- [x] Alembic migration for `events_log` and `runs` tables
- [x] Fix 5 test failures (dashboard table init in test fixtures)
- [x] Fix frontend-backend type mismatches (PortfolioSnapshot, Position, Order fields)
- [x] Fix API client URL mismatches (portfolio endpoint, getByCycleId)
- [x] Implement `POST /api/runs/trigger` (dry-run) and `POST /api/runs/trigger-live` (live cycle); Dashboard Home has Dry Run and Live Run buttons
- [x] Deployment: US-1.8 implemented (Docker, port 8000); deploy to VPS per `docs/DASHBOARD_DEPLOYMENT.md`
- [x] Phase 1.5 Analytics Lite: Decision Explorer, run diff, next-run countdown, P&L
- [x] Full API: decisions (incl. pipeline waterfall), moderation, risk, opportunity, outcomes, stop-loss, performance, costs, api-usage, system (state, trigger, pause, resume); status returns state and paused
- [x] 7 pages: Dashboard Home (system state badge, Dry Run/Live Run buttons), Universe, Run History, Portfolio, Opportunity Pipeline, Order Management, Costs
- [x] Design: terminal palette #0d1117, #58a6ff, #d4a017, subtle grid background

**Phases 2–4 (future):** Analytics & Insights; ML & Advanced (backtesting UI, anomaly detection, custom alerts); Interactive Control (manual run, strategy tuning UI, Slack mirror).

---

**US-1.8: Dashboard VPS Deployment**
**Value:** Operational visibility on live VPS; no domain required
**Effort:** Small (1–2 days)
**Data Sources:** Same DB as agent (shared volume)
**Stage:** Delivered

**Detailed plan:** `docs/DASHBOARD_DEPLOYMENT.md`

**Status (2026-03-10):** Delivered. Dashboard running on VPS: operator runs the deployment checklist in the plan (pull, `ufw allow 8000/tcp`, `docker compose up -d --build`); then dashboard is available at `http://YOUR_VPS_IP:8000`.

**Acceptance Criteria:**
- [x] Dashboard service added to docker-compose; shares `./data` volume with agent
- [x] Frontend built in Dockerfile (multi-stage); FastAPI serves static files
- [x] Access via `http://YOUR_VPS_IP:8000` (VPS IP — recommended; no domain)
- [x] Firewall: port 8000 documented and included in deployment commands (`ufw allow 8000/tcp`)
- [x] Activity feed (SSE), portfolio, runs, universe pages load correctly (relative API URLs work from VPS IP)
- [x] Deployment complete checklist in `DASHBOARD_DEPLOYMENT.md`; dashboard running on VPS once operator executes it

**Domain options:** VPS IP (recommended), purchase domain for HTTPS, or nginx reverse proxy. See deployment plan.

---

### P2 — Medium (Calibration, Portfolio, Signals, Validation)

**US-2.3: Moderator Effectiveness Analysis**
**Value:** Understand which moderator adds value; informs cost optimisation  
**Effort:** Small (2–3 days)  
**Data Sources:** moderation_logs, trade_outcomes  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Track: trades GPT-4o blocked that would have lost (correct) vs made money (opportunity cost); same for Gemini
- [ ] Monthly report: moderator value-add vs API cost
- [ ] Flag if moderator blocks wrong >60% of the time

---

**US-3.2: Enhanced Regime Detection**
**Value:** Regime-aware strategy selection improves hit rate  
**Effort:** Medium (3–4 days)  
**Data Sources:** Existing macro (VIX, S&P, yields)  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Continuous regime score (not binary BULL/BEAR/SIDEWAYS)
- [ ] Inputs: VIX level/trend, S&P vs 50/200 MA, yield curve slope
- [ ] Regime feeds dynamic strategy weighting (US-2.2); bull→momentum, bear→mean-reversion, transition→factor
- [ ] Logged for post-hoc analysis

**Technical Approach:** Weighted composite score; transparent, interpretable.

---

**US-3.3: Correlation-Aware Trade Screening**
**Value:** Prevents positions that duplicate existing risk exposure  
**Effort:** Small (2–3 days)  
**Data Sources:** Historical returns from market_data_cache  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Before BUY: correlation of candidate with each existing position
- [ ] If avg correlation with portfolio > 0.6, flag "high correlation" to Claude and moderators
- [ ] Soft signal in risk manager (existing 0.7 portfolio veto remains)

---

**US-4.1: Volume-Weighted Signals**
**Value:** Volume confirms price moves; zero-cost enhancement  
**Effort:** Small (2–3 days)  
**Data Sources:** Existing yfinance OHLCV (volume already fetched)  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] OBV; volume SMA ratio (current / 20-day avg)
- [ ] Sub-strategy: high-volume breakouts +10; volume < 50% avg = -10
- [ ] Logged in indicators output

---

**US-4.2: Earnings Calendar Integration**
**Value:** Avoid buying before earnings; position for post-earnings drift  
**Effort:** Medium (3–4 days)  
**Data Sources:** yfinance earnings calendar (free)  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Fetch next earnings date per candidate
- [ ] Flag "earnings imminent" if within 5 trading days
- [ ] Post-earnings drift signal (beat estimates, within 10 days)
- [ ] Config: `avoid_pre_earnings: true/false`

---

**US-5.2: Parameter Sensitivity Analysis**
**Value:** Focus tuning on parameters that matter  
**Effort:** Medium (3–4 days)  
**Data Sources:** Backtesting engine output  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Vary RSI, MA periods, strategy weights, allocation limits
- [ ] Heat maps: return/Sharpe sensitivity
- [ ] Document robust vs fragile parameter ranges

---

**US-6.1: Gradient-Boosted Trade Scoring**
**Value:** Potentially +3–7% annual; requires 500+ trade outcomes  
**Effort:** Large (investigation + implementation); investigate before committing  
**Data Sources:** trade_outcomes, strategy_decisions, indicators, fundamentals  
**Stage:** Planned  

**Investigation (before building):**
- [ ] Literature review; feature importance on trade data
- [ ] Cross-validation >5% improvement over current scoring
- [ ] If negative, skip and document

**Implementation (if passes):**
- [ ] XGBoost: indicators + fundamentals + sentiment → 10-day forward return
- [ ] Walk-forward retraining (monthly, trailing 6 months)
- [ ] Output as additional signal to Claude (not replacement); feature importance; fallback if degrades

---

### P3 — Lower priority

**US-4.3: Sector Rotation Signal**
**Value:** Sector momentum over long term  
**Effort:** Medium (3–5 days)  
**Data Sources:** Sector ETFs via yfinance (XLK, XLF, etc.)  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Relative performance of 11 GICS sectors via ETF proxies
- [ ] 3-month sector momentum ranking; overweight top 3, underweight bottom 3 in screening
- [ ] Sector momentum score to Claude as context

---

**US-6.2: Trade Journal Embeddings & Similarity Search**
**Value:** "Have we seen this pattern before?" context  
**Effort:** Medium (3–5 days)  
**Data Sources:** Existing markdown trade journals  
**Stage:** Planned  

**Acceptance Criteria:**
- [ ] Embeddings per journal entry; similarity search for new proposals
- [ ] Show outcomes of similar trades to Claude and moderators
- [ ] Store embeddings (vector column or file)

---

**US-6.3: Reinforcement Learning Investigation**
**Value:** Uncertain; investigate only  
**Effort:** Investigation (3–5 days)  
**Data Sources:** Academic literature, backtesting results  
**Stage:** Planned  

**Investigation Criteria:**
- [ ] Review FinRL-DeepSeek, CVaR-PPO; assess data and interpretability
- [ ] Proceed only if expected Sharpe improvement > 0.3 with interpretable policy
- [ ] Document findings regardless

---

**US-3.4: Universal Opportunity Value (UOV) Ranking and Queueing**
**Value:** Solves capital saturation; deterministic opportunity ranking and queue  
**Effort:** Medium  
**Data Sources:** strategy_decisions, moderation_logs, risk_decisions, sub-strategy, sentiment, instruments  
**Stage:** Delivered  

**Status (2026-03-03):** Delivered  

**Delivered Scope:**
- [x] UOV hybrid score (uov_raw), z-score (uov_z), stage penalties (uov_final), EWMA (uov_ewma)
- [x] Shadow/active in settings.yaml; active mode ranked BUY execution; queue + TTL
- [x] Conservative swap suggestions (delta_z ≥ 1.0); no autonomous SELL
- [x] Tables: opportunity_score_snapshots, opportunity_queue; cycle output: opportunity_ranking, queued_candidates, swap_candidates

---

## Resource allocation

### Team & constraints

| Resource | Availability | Strengths | Constraints |
|----------|-------------|-----------|-------------|
| **Project Lead** | Part-time (evenings/weekends) | PhD Mathematics, data science in finance, strategy | Time-limited, final approver |
| **Claude Code Opus 4.6** | Cloud, primary | Architecture, complex logic, strategy, investigation | Pro tier limits |
| **Codex 5.3+** | Local VS Code, secondary | Implementation, tests | May need review |

### Task assignment

| Task Type | Primary | Reviewer |
|-----------|---------|----------|
| Architecture & complex logic | Claude Code | Project Lead |
| New DB models & migrations | Claude Code | Codex (tests) |
| Signal/indicator additions | Codex | Claude Code |
| Dashboard & reporting | Codex | Project Lead |
| ML investigation & maths | Claude Code + Project Lead | Project Lead |
| Tests for new features | Developer who builds | Other developer |
| VPS deployment & ops | Project Lead | — |

---

## Next sprint focus

**Completed:**
- **US-1.7** — Dashboard full spec merged to main
- **US-1.4** — POC deployed to VPS (Docker, first cycle logged, health/backup confirmed)

**Immediate (current focus):**
- **US-4.4** — Agentic Research: **Delivered**. All 3 members (Strategy, Skeptic, Risk) have tool-use loops; 5 tools; shared budget; 37 tests. See `docs/AGENTIC_RESEARCH.md`.
- **US-2.4** — Nemotron integration investigation (evaluation only; no production switch). See `docs/Nemotron_3_Super_Integration_Investigation.md`.

**Deferred (await data or later sprint):**
- **US-2.1 / US-2.2** — Conviction calibration and dynamic strategy weighting (requires ~50 trades)
- **US-5.2 prep** — Parameter sensitivity harness
- **US-1.6** — Slack NL trade commands (Phase 2 chat)
- **US-1.9** — Conversational trading workflow (multi-turn Slack + dashboard chat)
- **US-4.5** — Proactive macro news intelligence (stateful macro layer + action planner)

**Delivery references:**
- `docs/ORDER_MANAGEMENT_PROJECT.md`
- `docs/BACKTESTING.md` (includes walk-forward validation)
- `docs/DASHBOARD_DEPLOYMENT.md`
- `docs/archived/CHAT_INTERFACE_PROJECT.md`
- `docs/archived/SLACK_TRADE_COMMANDS_PROJECT.md`
- `docs/archived/BACKTESTING_PROJECT_PLAN.md`
- `docs/archived/DASHBOARD_VISUALISATION_PROJECT.md`
- `docs/archived/AGENTIC_RESEARCH_PROJECT.md`, `docs/archived/AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md`
- `docs/Nemotron_3_Super_Integration_Investigation.md`

---

## Integration guarantees

All roadmap items integrate with the existing POC:

1. **Database:** New tables via Alembic migrations; no breaking changes to existing schema.  
2. **Pipeline:** New steps as post-cycle or pre-strategy hooks; orchestrator flow unchanged.  
3. **Config:** New keys in settings.yaml with defaults; existing config unchanged.  
4. **Tests:** New features use in-memory SQLite fixture pattern.  
5. **Fallback:** Every feature has a disable switch and falls back to current behaviour.  
6. **Logging:** New computations logged to database for audit.

The POC runs continuously and accumulates data while we add features in priority order.

---

## Data Enrichment

**Instrument enrichment (delivered):** ~5,477 US equities have sector, market_cap, industry, and business_summary from bulk/backfill. The strategy prompt uses Instrument as fallback when yfinance returns sparse data. For future updates (new tickers, additional fields, UK expansion, stale-data refresh), see [SEED_ENRICHMENT_PLAN.md](SEED_ENRICHMENT_PLAN.md#future-enrichment-and-expansion).

---

## Related Notes

- [Architecture](ARCHITECTURE.md) — pipeline flow, state machine, database schema
- [Agentic Research](AGENTIC_RESEARCH.md) — US-4.4 tool access plan (Brave + Tavily)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md) — US-1.9 unified multi-turn Slack/dashboard chat plan
- [Proactive Macro News Intelligence](PROACTIVE_MACRO_NEWS_INTELLIGENCE.md) — US-4.5 proactive macro scanning/state/signal plan
- [Nemotron Investigation](Nemotron_3_Super_Integration_Investigation.md) — candidate model evaluation plan and promotion gates
- [Governance](GOVERNANCE.md) — risk rules, cost controls, audit trail
- [Competitive Analysis](COMPETITIVE_ANALYSIS.md) — positioning vs alternatives
- [Presentation](PRESENTATION.md) — stakeholder deck overview
