---
tags: [backtesting, validation, walk-forward]
status: current
last_updated: 2026-03-10
---

# Walk-Forward Validation

> Multi-fold time-series validation to assess strategy stability and gate deployments.

## Purpose

Test the strategy across non-overlapping time windows so that performance claims are not overfitted to a single historical period. The promotion report turns walk-forward results into a go/no-go deployment decision.

## What is walk-forward validation?

**Walk-forward validation** is a way of testing a strategy on history by splitting time into **non-overlapping windows** and evaluating performance on each window separately. Unlike a single backtest over the full period, walk-forward:

- Runs the **same strategy** (and config) on multiple **test windows** (e.g. Year 1, Year 2, Year 3).
- Aggregates metrics **across folds** (e.g. mean/min/max Sharpe, mean drawdown).
- Produces a **promotion report** that recommends “safe to deploy” or “hold” based on whether the strategy meets criteria (e.g. Sharpe, drawdown, hit rate, excess return vs benchmark) across folds.

In this project we do **not** retrain a model between folds; the policy is deterministic and fixed. So “walk-forward” here means: *run the backtest engine on each time fold, collect metrics, and combine them* to assess stability and avoid overfitting to one period.

---

## Why it is important

1. **Reduces overfitting to one period**  
   A strategy that works only in 2020–2021 but fails in 2022–2023 will show up when we look at per-fold metrics. Single full-period backtests can hide that.

2. **Stability of performance**  
   We care not only that average Sharpe is acceptable, but that it is acceptable in **multiple** periods. Walk-forward gives mean, min, and max across folds so we can see dispersion.

3. **Release gating**  
   The promotion report (see below) turns walk-forward results into a clear **go/no-go** for deploying strategy or config changes. That supports governance and avoids deploying changes that only looked good on one slice of history.

4. **Alignment with best practice**  
   In quantitative finance, validating on out-of-sample time periods (rather than a single random split) is standard. Walk-forward implements that for our pipeline.

---

## How it is implemented

### Location and entrypoints

- **Module:** `src/backtesting/walk_forward.py` (splits, runner, aggregation).
- **Promotion report:** `src/backtesting/promotion_report.py`.
- **CLI:**  
  `poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward [--synthetic]`

With real data (default): if `data/backtest/` has no CSVs, the CLI fetches from yfinance and caches to CSV.  
  Writes results under the configured or default output dir.

### Main components

| Component | Role |
|-----------|------|
| **make_splits()** | Builds a list of `WalkForwardSplit` (fold_id, test_start, test_end). You specify start_date, end_date, n_folds, and test_days (e.g. 252 ≈ 1 year). Splits are non-overlapping calendar windows. |
| **run_walk_forward()** | For each split, loads bars for that window (from cache or from disk), runs `BacktestEngine`, and collects `{ fold_id, test_start, test_end, metrics }`. |
| **aggregate_fold_metrics()** | Takes the list of per-fold metrics and computes, for each numeric metric, `*_mean`, `*_min`, `*_max` across folds, plus `n_folds`. |
| **write_promotion_report()** | Writes a markdown report and returns a recommendation: **"safe to deploy"** or **"hold"**. Criteria (configurable) typically include: Sharpe ≥ threshold, max drawdown ≤ threshold, hit rate ≥ threshold, and (optionally) positive excess return vs benchmark. |

### Flow

1. User runs CLI with `--walk-forward` (and optionally `--synthetic` for synthetic bars).
2. Config supplies tickers, date range, seed, and backtest params.
3. `make_splits()` produces e.g. 3 folds (e.g. 2020, 2021, 2022).
4. `run_walk_forward()` runs the backtest engine on each fold and collects metrics.
5. `aggregate_fold_metrics()` computes mean/min/max across folds.
6. `write_promotion_report()` evaluates criteria and writes `promotion_report.md`; CLI prints the recommendation and aggregate metrics.
7. Output dir also contains `walk_forward_results.json` (aggregate + per-fold metrics).

### Scenario configs

Scenario YAMLs under `backtests/scenarios/` (e.g. `bull.yaml`, `bear.yaml`, `sideways.yaml`) define date ranges and tickers for regime-specific runs. You can run walk-forward with a scenario:  
`--scenario bull` loads `backtests/scenarios/bull.yaml` and uses that config (including dates) for the run.

---

## How it benefits this project

1. **Quantitative release gate**  
   Strategy or config changes can be required to pass walk-forward (and promotion report) before being deployed, so we rely on evidence across multiple periods rather than a single backtest.

2. **Clear audit trail**  
   The promotion report and `walk_forward_results.json` document exactly what was tested and why the recommendation was “safe to deploy” or “hold”.

3. **Future calibration**  
   Once we have live data, we can compare walk-forward results on “recent” folds to actual live performance to validate that the backtest is realistic and to tune parameters (e.g. US-2.1, US-2.2).

4. **Regime and scenario analysis**  
   Running walk-forward on bull/bear/sideways scenarios helps assess whether the strategy is robust across regimes and supports regime-aware improvements (e.g. US-3.2).

---

## Related Notes

- [Backtesting Engine](BACKTESTING.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-5.1, US-5.2
- [Governance & Audit Trail](GOVERNANCE.md)
