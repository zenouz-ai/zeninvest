---
title: Backtesting Engine
tags: [backtesting, validation, testing]
status: active
last_updated: 2026-03-29
user_stories: [US-5.1]
related: [ARCHITECTURE.md]
---

# Backtesting Engine

> Replay trading strategies on historical data to validate performance before live deployment.

## Purpose

**Backtesting** is the practice of running a trading strategy on historical market data to see how it would have performed in the past. Instead of executing real orders, a **paper broker** simulates fills (e.g. at the next day’s open, with configurable slippage), and the system records an **equity curve** and **trade list** as if the strategy had been live.

This project’s backtesting system addresses the **biggest maturity gap**: lack of historical evidence of edge. Current pipeline quality is strong (orchestration, moderation, risk controls, execution logging), but without backtesting and walk-forward validation:
- Parameter changes are difficult to justify
- Apparent improvements can be noise
- Risk of overfitting rises
- Live capital deployment confidence remains limited

In this project, backtesting:
- Replays **daily bars** for a fixed universe of tickers over a date range
- Rebuilds **signals at each date** using only data available at that time (no lookahead)
- Uses a **deterministic, LLM-free policy** (e.g. close vs SMA rules) so runs are reproducible and cheap
- Applies **portfolio and risk constraints** (cash floor, max positions, slippage) to mimic live behaviour

---

## Architecture

### Components

| Component | Role |
|-----------|------|
| **io** | Load daily OHLCV (and optional benchmark) from CSV or generate synthetic bars; `check_no_lookahead()` for leakage checks. |
| **broker** | `PaperBroker`: tracks cash and positions, fills orders at next open with configurable slippage (bps), records `Fill` with cost basis for PnL. |
| **engine** | `BacktestEngine`: loops over dates, builds daily bars and indicators (e.g. SMA), runs deterministic policy, submits orders, processes fills, records equity curve and trades. |
| **metrics** | `compute_metrics()`: Sharpe, Sortino, max drawdown, CAGR, hit rate, turnover, optional excess vs benchmark. |
| **policies** | `DeterministicPolicy`: LLM-free rules (e.g. BUY when close > SMA, SELL when close < SMA) with configurable SMA period and max positions. |

### Data and Assumptions

**Frequency:** Daily bars only (v1).

**Fill model:** Next-day open plus fixed slippage (bps).

**No lookahead bias:** At each date, only data on or before that date is used to compute signals. Strict feature timestamps and unit tests specifically guard against lookahead.

**Reproducibility:** Every run uses an explicit **seed**; same config + seed produce identical results. This requirement prevents noise from affecting comparisons.

**Data sources:**
- If no CSV files exist in `data/backtest/<TICKER>.csv`, the CLI automatically fetches OHLCV from **yfinance** for the config date range.
- OHLCV is cached to CSV for subsequent runs to reduce API load.
- Delete the CSV files to force a refresh.
- Corporate actions adjustments come from provider data.

**Cost realism:** Include spread/slippage/fees assumptions with configurable sensitivity ranges (default: fixed bps by liquidity tier).

**Reproducible splits:** Rolling walk-forward splits (train/validate/test by time, not random split) with fixed split schema and seed control.

---

## Implementation

### Entrypoints

**Package location:** `src/backtesting/`

**CLI commands:**

```bash
# Single run with default config
poetry run python -m src.backtesting.main --config backtests/default.yaml

# Synthetic data (for regression testing)
poetry run python -m src.backtesting.main --synthetic

# Walk-forward validation with promotion report
poetry run python -m src.backtesting.main --walk-forward

# Scenario analysis (bull/bear/sideways)
poetry run python -m src.backtesting.main --scenario bull|bear|sideways

# Custom output directory
poetry run python -m src.backtesting.main --config backtests/default.yaml --output-dir <path>
```

### Outputs (per run)

Every backtest produces four artifacts in a timestamped results directory:

- **`results.json`** — Summary metrics including CAGR, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure.
- **`trades.csv`** — Every simulated fill (timestamp, ticker, side, quantity, price, value, pnl_gbp).
- **`equity_curve.csv`** — Date and portfolio value.
- **`run_metadata.json`** — Config hash, commit hash, seed, timestamp.

Benchmark comparison (e.g. SPY buy-and-hold baseline) is included in every report when available.

### Strategy Proxy

**Phase 2 — LLM-free deterministic policy:**
- Deterministic synthesis heuristic from sub-strategy outputs (momentum, mean reversion, factor)
- Optional calibrated conviction mapping
- Optional moderation/risk proxy toggles (in future evolution)
- Allows backtests to run at scale without real LLM calls

**Benchmark comparison:**
- Excess return and drawdown vs SPY or configurable baseline
- Risk-adjusted metrics for regime-aware improvements

**Scenario profiles:**
- Bull, bear, and sideways sample periods for regime testing
- Different date windows show how strategy behaves in different regimes

---

## Technical Principles

1. **No lookahead bias**
   Indicators and signals only use data available at decision time. Strict enforcement via unit tests for leakage checks.

2. **Deterministic and reproducible**
   Same config + seed produces identical results across multiple runs. Essential for reliable parameter tuning.

3. **Cost realism**
   Include spread/slippage/fees assumptions with configurable sensitivity ranges. Conservative and optimistic bands help identify fragility.

4. **Config-driven**
   Backtest behaviour is toggled via `backtests/default.yaml` and scenario profiles; reuses existing strategy/risk configuration values.

5. **Fail-closed promotion**
   If walk-forward evidence is weak (e.g. Sharpe below threshold, drawdown exceeds bounds, hit rate unstable), do not promote strategy changes to live. Quantitative evidence is mandatory.

---

## Validation and Acceptance Criteria

- [x] End-to-end backtest run completes for 5+ years daily data without errors.
- [x] Walk-forward report generated with at least 3 rolling folds.
- [x] Outputs include: CAGR, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure.
- [x] Benchmark comparison included in every report.
- [x] Leakage checks: no future data access paths in strategy/risk inputs.
- [x] Determinism check: repeated run with same seed yields identical results.
- [x] CI tests cover core engine, fill logic, metric calculations, and split logic.

---

## Collaborative Development

This project is built and maintained collaboratively:

**Claude Code (primary):**
- Backtest architecture and simulation model assumptions
- Validation methodology (walk-forward, leakage guards, metrics interpretation)
- Statistical sanity checks and promotion criteria

**Codex (primary):**
- Engine implementation, CLI wiring, data loading plumbing
- Test suite and regression fixtures
- Integration with existing config/logging/docs

**Shared review responsibilities:**
- Assumptions review before first run
- Result interpretation review before deployment
- Joint sign-off for release gating rules

---

## Benefits

1. **Quantitative release gate**
   Strategy or risk changes must pass a backtest and walk-forward check (e.g. Sharpe above threshold, drawdown and hit rate within bounds) before going live. This closes the evidence gap.

2. **Calibration and tuning**
   Once backtest and live results are compared, calibration is possible for conviction, sizing, and strategy weights (e.g. US-2.1, US-2.2 in roadmap). Recent backtest windows can be compared to actual outcomes.

3. **Scenario and regime analysis**
   Scenario configs (bull, bear, sideways) and different date windows show strategy behaviour in different regimes, supporting regime-aware improvements (e.g. US-3.2).

4. **Transparency and audit**
   Every run is reproducible (seed + config) and artefacts are stored for audit. Parameter sweep registries and experiment tracking prevent overfitting through repeated tuning.

5. **Future extensions**
   The same engine can later plug in reused sub-strategy logic (momentum, mean reversion, factor) and risk rules from the live pipeline for closer alignment between backtest and production.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Overfitting through repeated tuning | Lock validation windows, track experiment registry, walk-forward discipline |
| Unrealistic execution assumptions | Run conservative and optimistic slippage bands, sensitivity analysis |
| Data leakage | Strict feature timestamps, unit tests for leakage checks, `check_no_lookahead()` validation |
| Complexity creep | Ship minimal reliable v1 before adding advanced microstructure (margin financing, borrow costs) |

---

## Success Metrics

- **Backtest runtime:** < 10 minutes for a 5-year daily run on standard dev machine
- **Reproducibility:** 100% deterministic for same config + seed
- **Research utility:** Every strategy PR includes backtest + walk-forward summary
- **Governance utility:** Promotion decision documented from quantitative evidence before deployment

---

## Walk-Forward Validation

> Multi-fold time-series validation to assess strategy stability and gate deployments.

### What is walk-forward validation?

**Walk-forward validation** tests a strategy across **non-overlapping time windows** and evaluates performance on each window separately. Unlike a single backtest over the full period, walk-forward:

- Runs the **same strategy** (and config) on multiple **test windows** (e.g. Year 1, Year 2, Year 3).
- Aggregates metrics **across folds** (e.g. mean/min/max Sharpe, mean drawdown).
- Produces a **promotion report** that recommends "safe to deploy" or "hold" based on whether the strategy meets criteria (e.g. Sharpe, drawdown, hit rate, excess return vs benchmark) across folds.

In this project we do **not** retrain a model between folds; the policy is deterministic and fixed. So "walk-forward" here means: *run the backtest engine on each time fold, collect metrics, and combine them* to assess stability and avoid overfitting to one period.

### Why it is important

1. **Reduces overfitting to one period** — A strategy that works only in 2020–2021 but fails in 2022–2023 will show up when we look at per-fold metrics.
2. **Stability of performance** — We care not only that average Sharpe is acceptable, but that it is acceptable in **multiple** periods.
3. **Release gating** — The promotion report turns walk-forward results into a clear **go/no-go** for deploying strategy or config changes.
4. **Alignment with best practice** — In quantitative finance, validating on out-of-sample time periods is standard.

### Walk-forward components

| Component | Role |
|-----------|------|
| **make_splits()** | Builds a list of `WalkForwardSplit` (fold_id, test_start, test_end). Non-overlapping calendar windows. |
| **run_walk_forward()** | For each split, loads bars for that window, runs `BacktestEngine`, and collects per-fold metrics. |
| **aggregate_fold_metrics()** | Computes `*_mean`, `*_min`, `*_max` across folds for each numeric metric, plus `n_folds`. |
| **write_promotion_report()** | Writes a markdown report and returns recommendation: **"safe to deploy"** or **"hold"**. |

**Module:** `src/backtesting/walk_forward.py` | **Promotion report:** `src/backtesting/promotion_report.py`

### Walk-forward flow

1. User runs CLI with `--walk-forward` (and optionally `--synthetic` for synthetic bars).
2. Config supplies tickers, date range, seed, and backtest params.
3. `make_splits()` produces e.g. 3 folds (e.g. 2020, 2021, 2022).
4. `run_walk_forward()` runs the backtest engine on each fold and collects metrics.
5. `aggregate_fold_metrics()` computes mean/min/max across folds.
6. `write_promotion_report()` evaluates criteria and writes `promotion_report.md`.
7. Output dir also contains `walk_forward_results.json` (aggregate + per-fold metrics).

### Scenario configs

Scenario YAMLs under `backtests/scenarios/` (e.g. `bull.yaml`, `bear.yaml`, `sideways.yaml`) define date ranges and tickers for regime-specific runs. Run walk-forward with a scenario: `--scenario bull` loads `backtests/scenarios/bull.yaml`.

---

## Related Notes

- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-5.1 (Core Engine) and US-5.2 (Walk-Forward + Promotion) status
