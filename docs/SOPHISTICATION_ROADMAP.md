# Sophistication Roadmap

**Last Updated:** 2026-03-03
**Owner:** Project Lead (PhD Mathematics, Data Science Manager in Finance)
**Developers:** Claude Code Opus 4.6 (cloud, primary), Codex 5.3+ (local VS Code, secondary)
**Principle:** Innovation, simplicity, elegance, transparency. No feature for technology's sake — every addition must materially improve quality.

---

## Current State: POC (v1.0)

The POC is a fully functional autonomous trading agent running on Trading 212 Practice API with a multi-LLM pipeline. All 128 tests pass. It is ready for VPS deployment to begin gathering live performance data.

**What the POC establishes:**
- End-to-end pipeline: Data → Screen → Strategy → Moderation → Risk → Execution → Journal
- Multi-LLM adversarial architecture (Claude + GPT-4o + Gemini)
- Deterministic risk guardrails with VETO power
- Deterministic UOV opportunity layer (shadow/active modes, ranked BUY queue, swap suggestions)
- Cost-aware degradation
- Comprehensive logging and audit trail

**What the POC lacks:**
- No feedback loop (doesn't learn from outcomes)
- No backtesting evidence
- No portfolio-level optimisation
- Static strategy parameters

---

## Design Principles for Evolution

1. **Measure before you build** — collect live data first, only build what the data justifies
2. **Incremental, not revolutionary** — each phase builds on the previous, no big rewrites
3. **POC compatibility** — all enhancements integrate with the existing pipeline architecture
4. **Evidence-based decisions** — no technique adopted without literature review and clear expected impact
5. **Personal quant experience first** — prioritise insights, dashboards, and learning over institutional features

---

## Phase 1: Foundation — Feedback Loop & Measurement (Weeks 1-6)

_Deploy POC, start collecting data, close the feedback loop._

### US-1.1: Performance Tracking Module
**Priority:** P0 (Critical)
**Value:** Enables all future improvements — can't improve what you can't measure
**Effort:** Medium (3-5 days)
**Data Sources:** Existing database (portfolio_snapshots, orders, strategy_decisions)
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Daily Sharpe ratio (rolling 30/60/90 day) computed from portfolio_snapshots
- [ ] Sortino ratio, max drawdown, Calmar ratio tracked
- [ ] Win rate by strategy (momentum, mean_reversion, factor) computed from filled orders
- [ ] Alpha vs S&P 500 benchmark tracked per snapshot
- [ ] Stored in new `performance_metrics` table with Alembic migration
- [ ] CLI command: `--performance` shows current metrics summary

**Integration Point:** Runs as post-cycle step in orchestrator, after portfolio snapshot.

---

### US-1.2: Trade Outcome Tracker
**Priority:** P0 (Critical)
**Value:** Links strategy decisions to actual P&L — the core data for calibration
**Effort:** Medium (3-5 days)
**Data Sources:** Existing orders + portfolio data
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Each BUY decision tracked until corresponding SELL/REDUCE
- [ ] Per-trade P&L (£ and %) recorded with holding period
- [ ] Claude's conviction score linked to actual outcome
- [ ] Each moderator's verdict linked to trade outcome (was GPT-4o right to block?)
- [ ] Risk decisions linked to outcomes (did resized trades perform differently?)
- [ ] New `trade_outcomes` table with Alembic migration

**Integration Point:** Updated on each SELL/REDUCE execution and daily snapshot.

---

### US-1.3: Performance Dashboard (CLI + Export)
**Priority:** P1 (High)
**Value:** Personal quant experience — immediate visibility into system behaviour
**Effort:** Small (2-3 days)
**Data Sources:** performance_metrics, trade_outcomes, cost_logs
**Developer:** Claude Code or Codex

**Acceptance Criteria:**
- [ ] `--dashboard` CLI command shows: portfolio value, Sharpe, win rate, costs, active positions
- [ ] CSV/JSON export for analysis in Jupyter notebooks
- [ ] Weekly email-style summary (rendered to journal markdown)

**Integration Point:** Extension of existing reporting module.

---

### US-1.4: Deploy POC to VPS
**Priority:** P0 (Critical)
**Value:** Begin gathering live market data and performance evidence
**Effort:** Small (1-2 days, following existing DEPLOYMENT.md)
**Data Sources:** N/A
**Developer:** Project Lead (manual deployment)

**Acceptance Criteria:**
- [ ] Docker container running on VPS
- [ ] Health check cron job active
- [ ] Backup script scheduled
- [ ] First successful cycle logged
- [ ] Monitoring access confirmed from local machine

---

### US-1.5: Chat Interface & Real-Time Trade Alerts (ChatOps Foundation)
**Priority:** P1 (High)
**Value:** Immediate operator visibility and control. Enables real-time awareness of BUY/SELL instructions and lays the foundation for human-in-the-loop controls via Slack/Telegram/email.
**Effort:** Medium (4-6 days)
**Data Sources:** Existing orchestrator decisions, `orders`, `system_state`, `risk_decisions`, `moderation_logs`
**Developer:** Codex (implementation) + Project Lead (security review)

**Acceptance Criteria:**
- [ ] Add a transport-agnostic notification service under `src/agents/notifications/`.
- [ ] Emit alerts for:
  - [ ] trade instruction approved (post moderation+risk, pre execution)
  - [ ] trade execution result (filled/dry_run/failed)
  - [ ] state machine transitions (ACTIVE/CAUTIOUS/HALTED)
  - [ ] critical cycle failures
- [ ] Provide at least two outbound channels in v1:
  - [ ] Slack webhook alerts
  - [ ] Email alerts (SMTP)
- [ ] Add channel configuration and feature flags in `config/settings.yaml`.
- [ ] Add secrets to `.env.example` with safe placeholders.
- [ ] Add retry + timeout + non-blocking send so notification failures never block trade execution.
- [ ] Add `notification_logs` table with status, channel, payload hash, and error fields.

**Phase 1 Scope (Outbound only):**
- Notify on instructed/executed trades and critical system events.

**Phase 2 Scope (Inbound chat commands):**
- [ ] Build command gateway for `/status`, `/pause`, `/resume`, `/force-sell <ticker>`.
- [ ] Add authentication and command allow-listing.
- [ ] Add full audit logging for all received commands.

**Integration Point:**
- Trigger from `Orchestrator._execute_trade()` and state transitions in the state machine.
- Reuse existing control actions already exposed by the CLI (`--status`, `--pause`, `--resume`, `--force-sell`).

---

## Phase 2: Calibration — Learning from Live Data (Weeks 4-10)

_Use accumulated live data to calibrate and tune. Requires ~50-100 completed trades._

### US-2.1: Conviction Calibration
**Priority:** P1 (High)
**Value:** Significant — if conviction 80+ trades win 70% but conviction 50-60 win only 45%, position sizing by calibrated conviction adds 2-5% annually
**Effort:** Medium (3-4 days)
**Data Sources:** trade_outcomes (from US-1.2), strategy_decisions
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Calibration curve: conviction score vs actual win rate (binned: 50-60, 60-70, 70-80, 80+)
- [ ] Minimum 30 trades per bin before activating calibration
- [ ] Position sizing adjusted by calibrated confidence: `size = base_size * calibration_factor`
- [ ] Logged to strategy_decisions for audit trail
- [ ] Falls back to current behaviour if insufficient data

**Technical Approach:** Simple logistic regression or empirical calibration curve. No ML needed.

---

### US-2.2: Dynamic Strategy Weighting
**Priority:** P1 (High)
**Value:** Moderate-High — stops allocating to strategies that aren't working in current regime
**Effort:** Medium (3-4 days)
**Data Sources:** trade_outcomes, strategy_decisions
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Rolling 30-day hit rate computed per sub-strategy (momentum, mean_reversion, factor)
- [ ] Weights adjusted proportionally: `new_weight = base_weight * rolling_hit_rate / avg_hit_rate`
- [ ] Minimum weight floor (15%) — no strategy drops below this
- [ ] Maximum weight cap (50%) — no strategy dominates
- [ ] Weight changes logged and visible in dashboard
- [ ] Configurable via settings.yaml: `dynamic_weighting: true/false`

**Technical Approach:** Exponentially weighted moving average of success rate. Simple, transparent, no ML.

---

### US-2.3: Moderator Effectiveness Analysis
**Priority:** P2 (Medium)
**Value:** Understand which moderator adds value — informs cost optimisation
**Effort:** Small (2-3 days)
**Data Sources:** moderation_logs, trade_outcomes
**Developer:** Codex

**Acceptance Criteria:**
- [ ] Track: "trades GPT-4o blocked that would have lost money" (correct blocks)
- [ ] Track: "trades GPT-4o blocked that would have made money" (opportunity cost)
- [ ] Same for Gemini
- [ ] Monthly report comparing moderator value-add vs API cost
- [ ] If a moderator's blocks are wrong >60% of the time, flag for review

---

## Phase 3: Portfolio Intelligence (Weeks 8-14)

_Move from individual stock picks to portfolio-level thinking._

### US-3.1: Risk-Parity Position Sizing
**Priority:** P1 (High)
**Value:** High — reduces portfolio volatility without reducing returns. Academic evidence is strong.
**Effort:** Medium (4-5 days)
**Data Sources:** Historical returns from market_data_cache
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Each position sized inversely proportional to its trailing 60-day volatility
- [ ] Target: equal risk contribution from each position
- [ ] Replaces Claude's ad-hoc allocation percentages for BUY sizing
- [ ] Claude still decides what to buy/sell; risk-parity decides how much
- [ ] Existing risk limits (max 15% per stock, etc.) still enforced as hard caps
- [ ] A/B comparison logged: risk-parity size vs Claude's proposed size

**Technical Approach:** `weight_i = (1/vol_i) / sum(1/vol_j)`. No optimiser library needed.

**Literature:** Maillard, Roncalli & Teiletche (2010) "The Properties of Equally Weighted Risk Contribution Portfolios"

---

### US-3.2: Enhanced Regime Detection
**Priority:** P2 (Medium)
**Value:** Moderate — current binary VIX rules miss nuance. Regime-aware strategy selection improves hit rate.
**Effort:** Medium (3-4 days)
**Data Sources:** Existing macro data (VIX, S&P, yields)
**Developer:** Claude Code or Codex

**Acceptance Criteria:**
- [ ] Replace binary BULL/BEAR/SIDEWAYS with continuous regime score
- [ ] Inputs: VIX level, VIX 20-day trend, S&P vs 50/200 MA, yield curve slope
- [ ] Regime score feeds into dynamic strategy weighting (US-2.2)
- [ ] Bull regime: favour momentum. Bear: favour mean-reversion. Transition: favour factor/quality
- [ ] Logged to database for post-hoc analysis

**Technical Approach:** Weighted composite score, not Hidden Markov Model (premature for data available). Keep it transparent and interpretable.

---

### US-3.3: Correlation-Aware Trade Screening
**Priority:** P2 (Medium)
**Value:** Moderate — prevents adding positions that duplicate existing risk exposure
**Effort:** Small (2-3 days)
**Data Sources:** Historical returns from market_data_cache
**Developer:** Codex

**Acceptance Criteria:**
- [ ] Before approving a BUY, compute correlation of candidate with each existing position
- [ ] If avg correlation with portfolio > 0.6, flag as "high correlation" to Claude and moderators
- [ ] Include in risk manager evaluation (soft signal, not hard veto — existing 0.7 portfolio veto remains)
- [ ] Reduces unintentional sector concentration that passes individual-stock checks

---

### US-3.4: Universal Opportunity Value (UOV) Ranking and Queueing
**Priority:** P1 (High)
**Value:** High — solves capital saturation by ranking approved BUYs across cycles and preserving deferred opportunities in a deterministic queue
**Effort:** Medium (implemented)
**Data Sources:** strategy_decisions, moderation_logs, risk_decisions, sub-strategy outputs, per-ticker sentiment, instruments
**Developer:** Codex

**Status (2026-03-03):** Delivered

**Delivered Scope:**
- [x] UOV hybrid score (`uov_raw`) from strategy/moderation/risk/sentiment/fundamental proxies
- [x] Cross-sectional z-score (`uov_z`) + stage penalties (`uov_final`)
- [x] EWMA smoothing (`uov_ewma`) with configurable half-life (default 6 cycles)
- [x] Shadow/active rollout switch in `settings.yaml`
- [x] Active mode ranked BUY execution under cash/slot constraints
- [x] Queue lifecycle with persistence, reranking, and TTL expiry
- [x] Conservative swap suggestions (`delta_z >= 1.0`) without autonomous SELL authority
- [x] Audit tables: `opportunity_score_snapshots`, `opportunity_queue`
- [x] Cycle output extensions: `opportunity_ranking`, `queued_candidates`, `swap_candidates`

---

## Phase 4: Signal Enhancement (Weeks 12-20)

_Better inputs to the pipeline, grounded in data we've now collected._

### US-4.1: Volume-Weighted Signals
**Priority:** P2 (Medium)
**Value:** Moderate — volume confirms price moves, reduces false signals. Data already fetched but unused.
**Effort:** Small (2-3 days)
**Data Sources:** Existing yfinance OHLCV (volume column already fetched)
**Developer:** Codex

**Acceptance Criteria:**
- [ ] Add OBV (On-Balance Volume) indicator
- [ ] Add volume SMA ratio (current volume / 20-day avg volume)
- [ ] Feed into sub-strategy scoring: high-volume breakouts get +10 score
- [ ] Low-volume signals penalised (volume < 50% of avg = -10 score)
- [ ] Logged in indicators output

**Rationale:** Volume is already downloaded by yfinance but not used (noted in DATA_RATIONALE.md). This is low-effort, zero-cost signal enhancement.

---

### US-4.2: Earnings Calendar Integration
**Priority:** P2 (Medium)
**Value:** Moderate — avoid buying before earnings (high vol event), or position for post-earnings drift
**Effort:** Medium (3-4 days)
**Data Sources:** yfinance earnings calendar (free)
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Fetch next earnings date for each candidate
- [ ] If earnings within 5 trading days: flag to Claude and moderators as "earnings imminent"
- [ ] Post-earnings drift signal: if stock beat estimates and is within 10 days post-earnings, mild BUY signal
- [ ] Configurable: `avoid_pre_earnings: true/false`

---

### US-4.3: Sector Rotation Signal
**Priority:** P3 (Low)
**Value:** Moderate over long term — institutional research shows sector momentum is real
**Effort:** Medium (3-5 days)
**Data Sources:** Sector ETF data via yfinance (XLK, XLF, XLV, etc.) — free
**Developer:** Codex

**Acceptance Criteria:**
- [ ] Track relative performance of 11 GICS sectors via ETF proxies
- [ ] Compute 3-month sector momentum ranking
- [ ] Overweight top 3 sectors, underweight bottom 3 in universe screening
- [ ] Feed sector momentum score to Claude as additional context

---

## Phase 5: Backtesting & Validation (Weeks 16-24)

_Build confidence in the system with historical evidence._

### US-5.1: Backtesting Engine
**Priority:** P1 (High) — but deliberately delayed until we have live data to validate against
**Value:** Critical for long-term confidence, but meaningless without calibrated strategies
**Effort:** Large (5-8 days)
**Data Sources:** yfinance historical data
**Developer:** Claude Code (architecture) + Codex (implementation)

**Acceptance Criteria:**
- [ ] Replay historical data through sub-strategy scoring (momentum, mean_rev, factor)
- [ ] Simulate risk rules, position sizing, portfolio constraints
- [ ] LLM calls mocked with simplified heuristic (backtesting 1000s of days with LLM calls is cost-prohibitive)
- [ ] Output: equity curve, Sharpe ratio, max drawdown, win rate
- [ ] Walk-forward validation: train on years 1-3, test on year 4-5
- [ ] Compare: our strategies vs buy-and-hold SPY

**Technical Approach:** Custom lightweight engine using pandas, not an external framework. Keeps us in control and avoids dependency bloat. Consider vectorbt only if performance is an issue.

**Why delayed:** Backtesting before calibration is misleading. We need live performance data (Phase 1-2) to know what to validate.

---

### US-5.2: Parameter Sensitivity Analysis
**Priority:** P2 (Medium)
**Value:** Understand which parameters matter most — focus tuning effort
**Effort:** Medium (3-4 days, depends on US-5.1)
**Data Sources:** Backtesting engine output
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Vary key parameters: RSI thresholds, MA periods, strategy weights, allocation limits
- [ ] Heat maps showing return/Sharpe sensitivity to each parameter
- [ ] Identify robust parameter ranges vs fragile ones
- [ ] Document which parameters are safe to tune vs which should be left alone

---

## Phase 6: Advanced Intelligence (Weeks 20-36)

_ML-assisted improvements, only if justified by accumulated data._

### US-6.1: Gradient-Boosted Trade Scoring
**Priority:** P2 (Medium) — investigate before committing
**Value:** Potentially high (+3-7% annual) but uncertain. Requires 500+ trade outcomes for meaningful training.
**Effort:** Large (5-8 days for investigation + implementation)
**Data Sources:** trade_outcomes, strategy_decisions, indicators, fundamentals
**Developer:** Claude Code (investigation) + Project Lead (mathematical validation)

**Investigation Criteria (before building):**
- [ ] Literature review: does XGBoost/LightGBM add value over simple heuristics for equity selection?
- [ ] Feature importance analysis on accumulated trade data
- [ ] Cross-validation showing >5% improvement over current scoring
- [ ] If investigation is negative, skip this and note findings

**Implementation Criteria (if investigation passes):**
- [ ] XGBoost model trained on: all indicators + fundamentals + sentiment → 10-day forward return
- [ ] Walk-forward retraining: monthly retrain on trailing 6 months
- [ ] Model output feeds as additional signal to Claude (not replacement)
- [ ] Feature importance dashboard for transparency
- [ ] Fallback to current scoring if model degrades

---

### US-6.2: Trade Journal Embeddings & Similarity Search
**Priority:** P3 (Low)
**Value:** Uncertain but intellectually interesting — "have we seen this pattern before?"
**Effort:** Medium (3-5 days)
**Data Sources:** Existing markdown trade journals
**Developer:** Claude Code

**Acceptance Criteria:**
- [ ] Generate embeddings for each trade journal entry
- [ ] On new trade proposal, find 3-5 most similar historical trades
- [ ] Show outcomes of similar trades to Claude and moderators as context
- [ ] Store embeddings in vector column or separate file

---

### US-6.3: Reinforcement Learning Investigation
**Priority:** P3 (Low) — investigate only, do not implement without strong evidence
**Value:** Uncertain. Academic results are mixed. RL agents are opaque and fragile.
**Effort:** Investigation only (3-5 days)
**Data Sources:** Academic literature, our backtesting results
**Developer:** Project Lead + Claude Code

**Investigation Criteria:**
- [ ] Review: FinRL-DeepSeek, CVaR-PPO approaches from 2025 literature
- [ ] Assess: do we have enough data? (typically need 10,000+ episodes)
- [ ] Assess: can we maintain transparency and interpretability?
- [ ] Decision gate: proceed only if expected Sharpe improvement > 0.3 with interpretable policy
- [ ] Document findings regardless of decision

---

## Resource Allocation & Delivery Timeline

### Team & Constraints

| Resource | Availability | Strengths | Constraints |
|----------|-------------|-----------|-------------|
| **Project Lead** | Part-time (evenings/weekends) | PhD Mathematics, data science in finance, strategic direction | Time-limited, final approver |
| **Claude Code Opus 4.6** | Cloud, primary developer | Architecture, complex logic, strategy code, investigation | Pro tier limits (frequent resets) |
| **Codex 5.3+** | Local VS Code, secondary | Longer runs, implementation tasks, tests | May be less accurate, needs review |

### Delivery Timeline

```
Week  1-2:  POC deployment to VPS (US-1.4) + Performance tracking (US-1.1)
Week  3-4:  Trade outcome tracker (US-1.2) + Performance dashboard (US-1.3)
Week  5-6:  Chat interface + real-time alerts (US-1.5)
Week  7-8:  Buffer / bug fixes from live running + data collection
Week  9-10: Conviction calibration (US-2.1) — needs ~50 trades first
Week 11-12: Dynamic strategy weighting (US-2.2) + Moderator analysis (US-2.3)
Week 13-14: Risk-parity sizing (US-3.1) + Volume signals (US-4.1)
Week 15-16: Enhanced regime detection (US-3.2) + Correlation screening (US-3.3)
Week 17-18: Earnings calendar (US-4.2) + Sector rotation (US-4.3)
Week 19-22: Backtesting engine (US-5.1) + Parameter sensitivity (US-5.2)
Week 23-26: ML investigation (US-6.1) — decision gate
Week 27-32: ML implementation (if justified) or alternative enhancements
Week 33-36: RL investigation (US-6.3), journal embeddings (US-6.2)
```

### Task Assignment Strategy

| Task Type | Primary Developer | Reviewer |
|-----------|------------------|----------|
| Architecture & complex logic | Claude Code | Project Lead |
| New database models & migrations | Claude Code | Codex (tests) |
| Signal/indicator additions | Codex | Claude Code (review) |
| Dashboard & reporting | Codex | Project Lead |
| ML investigation & maths | Claude Code + Project Lead | Project Lead (final) |
| Tests for new features | Developer who builds it | Other developer |
| VPS deployment & ops | Project Lead | N/A |

---

## Priority Matrix

| # | User Story | Value | Feasibility | Effort | Data Needed | Priority |
|---|-----------|-------|-------------|--------|-------------|----------|
| 1.4 | Deploy POC to VPS | Critical | Easy | S | None | **P0** |
| 1.1 | Performance tracking | Critical | Easy | M | Existing DB | **P0** |
| 1.2 | Trade outcome tracker | Critical | Easy | M | Existing DB | **P0** |
| 1.3 | Performance dashboard | High | Easy | S | US-1.1, 1.2 | **P1** |
| 1.5 | Chat interface + trade alerts | High | Easy-Med | M | Existing DB + orchestrator events | **P1** |
| 2.1 | Conviction calibration | High | Medium | M | ~50 trades | **P1** |
| 2.2 | Dynamic strategy weighting | High | Medium | M | ~50 trades | **P1** |
| 3.1 | Risk-parity sizing | High | Easy | M | Historical prices | **P1** |
| 5.1 | Backtesting engine | High | Medium | L | yfinance history | **P1** |
| 2.3 | Moderator effectiveness | Medium | Easy | S | ~100 trades | **P2** |
| 3.2 | Enhanced regime detection | Medium | Medium | M | Existing macro | **P2** |
| 3.3 | Correlation-aware screening | Medium | Easy | S | Historical prices | **P2** |
| 4.1 | Volume-weighted signals | Medium | Easy | S | Already fetched | **P2** |
| 4.2 | Earnings calendar | Medium | Easy | M | yfinance (free) | **P2** |
| 5.2 | Parameter sensitivity | Medium | Medium | M | Backtest engine | **P2** |
| 6.1 | ML trade scoring | Medium | Hard | L | 500+ trades | **P2** |
| 4.3 | Sector rotation signal | Low-Med | Easy | M | ETF data (free) | **P3** |
| 6.2 | Journal embeddings | Low | Medium | M | Trade journals | **P3** |
| 6.3 | RL investigation | Low | Hard | M | Academic lit | **P3** |

---

## Integration Guarantees

All roadmap items are designed to integrate with the existing POC architecture:

1. **Database**: New tables via Alembic migrations. No changes to existing schema.
2. **Pipeline**: New steps added as post-cycle or pre-strategy hooks. Orchestrator pipeline unchanged.
3. **Config**: New settings added to settings.yaml with sensible defaults. Existing config unchanged.
4. **Tests**: Every new feature includes tests using existing in-memory SQLite fixture pattern.
5. **Fallback**: Every new feature has a disable switch and falls back to current behaviour.
6. **Logging**: All new computations logged to database for audit trail.

The POC deployed today will run continuously and accumulate data while we build Phase 1-6 features in parallel.
