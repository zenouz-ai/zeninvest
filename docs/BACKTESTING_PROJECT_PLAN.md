# Backtesting Project Plan (Biggest Gap)

## Objective

Design and implement a robust, reproducible backtesting capability that closes the largest maturity gap in the project: **lack of historical evidence of edge**.

This project is intended to be built collaboratively with **Claude Code** (architecture/math-heavy components) and **Codex** (implementation/testing/integration), then used as a release gate before strategy changes are promoted to live cycles.

---

## Why this is the biggest gap

Current pipeline quality is strong (orchestration, moderation, risk controls, execution logging), but there is still no walk-forward evidence that strategy changes improve outcomes out-of-sample.

Without backtesting + validation:
- parameter changes are difficult to justify,
- apparent improvements can be noise,
- risk of overfitting rises,
- live capital deployment confidence remains limited.

---

## Scope

## Phase 1 — Core Replay Engine (Week 1)

### Functional scope
- Replay daily bars for a universe of tickers across historical windows.
- Reconstruct candidate set + indicators + factor inputs at each time step (no lookahead).
- Run deterministic sub-strategy stack (momentum, mean reversion, factor).
- Apply risk constraints and portfolio limits (cash floor, max stock/sector, drawdown states).
- Simulate order fills with configurable slippage/spread assumptions.
- Track equity curve and per-trade ledger.

### Deliverables
- `src/backtesting/engine.py` (event loop/replay coordinator)
- `src/backtesting/broker.py` (paper broker, fills, cash/positions)
- `src/backtesting/metrics.py` (Sharpe, Sortino, drawdown, hit rate, turnover)
- `src/backtesting/io.py` (dataset loading and integrity checks)
- CLI entrypoint for backtest runs and result export

---

## Phase 2 — Strategy Proxy + Portfolio Validation (Week 1–2)

### Functional scope
- Implement **LLM proxy policy** for historical runs:
  - deterministic synthesis heuristic from sub-strategy outputs,
  - optional calibrated conviction mapping,
  - optional moderation/risk proxy toggles.
- Support benchmark comparison (SPY buy-and-hold baseline).
- Add scenario profiles (bull/bear/sideways sample periods).

### Deliverables
- `src/backtesting/policies/` with deterministic policy variants
- Benchmark report with excess return, drawdown, and risk-adjusted metrics
- Export artifacts (`results.json`, `trades.csv`, `equity_curve.csv`)

---

## Phase 3 — Walk-Forward Validation + Research Harness (Week 2)

### Functional scope
- Rolling walk-forward splits (train/validate/test by time, not random split).
- Parameter sweep hooks for sensitivity analysis.
- Stability checks: performance dispersion across regimes and universes.
- Drift check: compare simulated recent window vs live behaviour.

### Deliverables
- Walk-forward runner with fixed split schema and seed control.
- Parameter sweep config + summary ranking.
- Promotion report template: "safe to deploy" vs "hold".

---

## Collaborative split: Claude Code vs Codex

### Claude Code (primary)
- Backtest architecture and simulation model assumptions
- Validation methodology (walk-forward, leakage guards, metrics interpretation)
- Statistical sanity checks and promotion criteria

### Codex (primary)
- Engine implementation, CLI wiring, data loading plumbing
- Test suite and regression fixtures
- Integration with existing config/logging/docs

### Shared review responsibilities
- Assumptions review before first run
- Result interpretation review before deployment
- Joint sign-off for release gating rules

---

## Technical design principles

1. **No lookahead bias**
   - Indicators/signals only use data available at decision time.
2. **Deterministic and reproducible**
   - Same config + seed => same results.
3. **Cost realism**
   - Include spread/slippage/fees assumptions with sensitivity ranges.
4. **Config-driven**
   - Backtest behaviour should be toggled via settings profiles.
5. **Fail-closed promotion**
   - If walk-forward evidence is weak, do not promote strategy changes.

---

## Data and assumptions

### Inputs
- Historical OHLCV from existing market data layer / cached datasets
- Existing strategy/risk configuration values
- Optional universe snapshots for realistic candidate availability

### Assumptions (explicit + configurable)
- Bar frequency: daily (initially)
- Fill model: close+slippage or next-open+slippage
- Spread model: fixed bps by liquidity tier (initial simplification)
- Corporate actions: adjusted prices from provider data

---

## Validation and acceptance criteria

- [ ] End-to-end backtest run completes for 5+ years daily data without errors.
- [ ] Walk-forward report generated with at least 3 rolling folds.
- [ ] Outputs include: CAGR, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure.
- [ ] Benchmark comparison included in every report.
- [ ] Leakage checks: no future data access paths in strategy/risk inputs.
- [ ] Determinism check: repeated run with same seed yields identical results.
- [ ] CI tests cover core engine, fill logic, metric calculations, and split logic.

---

## Integration points with existing system

- Reuse strategy sub-signal functions for consistency.
- Reuse risk manager rule logic where possible.
- Persist backtest summaries in a dedicated table (future migration).
- Add CLI command (proposed):
  - `poetry run python -m src.backtesting.main --config backtests/default.yaml`

---

## Week-ahead execution plan (two main user stories)

## User Story A (Next Week): Chat Interface
- Finalise outbound alert event schema.
- Implement Slack + email transport adapters.
- Add non-blocking notification service and retry behavior.
- Wire orchestrator and state transition hooks.

## User Story B (Next Week): Backtesting Foundations
- Build replay loop and broker core.
- Implement deterministic policy proxy (LLM-free simulation mode).
- Produce first baseline benchmark report on a fixed ticker subset.
- Publish limitations and assumptions in report footer.

---

## Risks and mitigations

- **Overfitting through repeated tuning** -> lock validation windows, track experiment registry.
- **Unrealistic execution assumptions** -> run conservative and optimistic slippage bands.
- **Data leakage** -> strict feature timestamps + unit tests specifically for leakage checks.
- **Complexity creep** -> ship minimal reliable v1 before adding advanced microstructure logic.

---

## Success metrics

- Backtest runtime: < 10 minutes for a 5-year daily run on standard dev machine.
- Reproducibility: 100% deterministic for same config/seed.
- Research utility: every strategy PR includes backtest + walk-forward summary.
- Governance utility: promotion decision documented from quantitative evidence.
