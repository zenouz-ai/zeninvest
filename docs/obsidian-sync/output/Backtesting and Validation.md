---
tags: [investment-agent, backtesting, validation, walk-forward]
status: active
last_updated: 2026-03-18
---

# Backtesting and Validation

Addresses the biggest maturity gap: lack of historical evidence of edge. Without backtesting, parameter changes are difficult to justify, apparent improvements can be noise, and risk of overfitting rises.

## What It Does

Replays daily bars for a universe of tickers over a date range. Rebuilds signals at each date using only data available at that time (no lookahead). Uses a deterministic, LLM-free policy so runs are reproducible and cheap. Applies portfolio and risk constraints (cash floor, max positions, slippage) to mimic live behaviour.

## Components

- **io** — load daily OHLCV from CSV or generate synthetic bars. Fetches from yfinance if CSVs missing, caches to `data/backtest/`.
- **PaperBroker** — tracks cash and positions, fills at next-day open + configurable slippage (bps), records cost basis for P&L.
- **BacktestEngine** — date loop, daily bars + indicators, deterministic policy, order submission, equity curve + trades.
- **DeterministicPolicy** — LLM-free rules (BUY when close > SMA, SELL when close < SMA), configurable SMA period and max positions.
- **Metrics** — Sharpe, Sortino, max drawdown, CAGR, hit rate, turnover, excess vs benchmark.

## Walk-Forward Validation

Tests the same strategy across non-overlapping time windows (e.g. Year 1, Year 2, Year 3). Aggregates metrics across folds (mean/min/max Sharpe, drawdown). Produces a promotion report: **"safe to deploy"** or **"hold"** based on whether metrics meet criteria across all folds.

Key principle: strategy that works only in 2020–2021 but fails in 2022–2023 gets flagged. Stability across periods matters more than peak performance in one.

## Technical Principles

1. **No lookahead bias** — strict feature timestamps, unit tests guard against leakage
2. **Deterministic** — same config + seed = identical results every time
3. **Cost realism** — configurable slippage, conservative and optimistic bands
4. **Config-driven** — all parameters in `backtests/default.yaml`
5. **Fail-closed promotion** — weak evidence = no promotion to live

## Outputs Per Run

- `results.json` — CAGR, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure
- `trades.csv` — every simulated fill
- `equity_curve.csv` — date + portfolio value
- `run_metadata.json` — config hash, commit hash, seed, timestamp
- Benchmark comparison (SPY buy-and-hold) included in every report

## Scenario Configs

Bull, bear, sideways YAMLs under `backtests/scenarios/`. Different date windows show regime-specific strategy behaviour.

## What Backtesting Enables

1. **Quantitative release gate** — strategy changes must pass backtest + walk-forward before going live
2. **Calibration foundation** — compare backtest to live results for conviction and sizing calibration (US-2.1, US-2.2)
3. **Regime analysis** — scenario configs reveal strategy behaviour across market conditions
4. **Audit** — every run reproducible (seed + config), artefacts stored

## Key Risks

- Overfitting through repeated tuning → locked validation windows, experiment registry
- Unrealistic execution assumptions → conservative/optimistic slippage bands
- Data leakage → strict timestamps, `check_no_lookahead()` validation

## Related Notes

- [[Project Overview]]
- [[Sophistication Roadmap]]
- [[Data Pipeline Rationale]]
