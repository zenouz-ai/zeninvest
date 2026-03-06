# Backtesting in the Investment Agent

## What is backtesting?

**Backtesting** is the practice of running a trading strategy on historical market data to see how it would have performed in the past. Instead of executing real orders, a **paper broker** simulates fills (e.g. at the next day’s open, with configurable slippage), and the system records an **equity curve** and **trade list** as if the strategy had been live.

In this project, backtesting:

- Replays **daily bars** for a fixed universe of tickers over a date range.
- Rebuilds **signals at each date** using only data available at that time (no lookahead).
- Uses a **deterministic, LLM-free policy** (e.g. close vs SMA rules) so runs are reproducible and cheap.
- Applies **portfolio and risk constraints** (cash floor, max positions, slippage) to mimic live behaviour.

---

## Why it is important

1. **Evidence gap**  
   Without backtesting, we only know how the system behaves in live or practice mode. We cannot say whether a parameter change (e.g. strategy weights, risk limits) would have helped or hurt over past years.

2. **Parameter and strategy discipline**  
   Backtests let us:
   - Justify strategy and risk parameter changes with quantitative results.
   - Avoid overfitting by using **walk-forward validation** (train/validate on one period, test on a later one).
   - Compare the strategy to a **benchmark** (e.g. SPY buy-and-hold) to measure excess return and risk-adjusted performance.

3. **Governance and release gating**  
   The backtesting pipeline produces a **promotion report** (e.g. “safe to deploy” vs “hold”) based on Sharpe, drawdown, hit rate, and excess return. That gives a clear gate before promoting strategy or config changes to live.

4. **Cost and speed**  
   Running thousands of days with real LLM calls would be expensive and slow. A **deterministic policy proxy** (e.g. simple rules from the same inputs the live strategy uses) makes large-scale backtests feasible and reproducible.

---

## How it is implemented

### Location and entrypoints

- **Package:** `src/backtesting/`
- **CLI:**  
  `poetry run python -m src.backtesting.main --config backtests/default.yaml`  
  Optional: `--synthetic` (use synthetic data), `--walk-forward`, `--scenario bull|bear|sideways`, `--output-dir <path>`.

### Main components

| Component | Role |
|-----------|------|
| **io** | Load daily OHLCV (and optional benchmark) from CSV or generate synthetic bars; `check_no_lookahead()` for leakage checks. |
| **broker** | `PaperBroker`: tracks cash and positions, fills orders at next open with configurable slippage (bps), records `Fill` with cost basis for PnL. |
| **engine** | `BacktestEngine`: loops over dates, builds daily bars and indicators (e.g. SMA), runs deterministic policy, submits orders, processes fills, records equity curve and trades. |
| **metrics** | `compute_metrics()`: Sharpe, Sortino, max drawdown, CAGR, hit rate, turnover, optional excess vs benchmark. |
| **policies** | `DeterministicPolicy`: LLM-free rules (e.g. BUY when close > SMA, SELL when close < SMA) with configurable SMA period and max positions. |

### Data and assumptions

- **Frequency:** daily bars only (v1).
- **Fill model:** next-day open plus fixed slippage (bps).
- **No lookahead:** at each date, only data on or before that date is used to compute signals.
- **Reproducibility:** every run uses an explicit **seed**; same config + seed produce the same results.
- **Data sources:** If no CSV files exist in `data/backtest/<TICKER>.csv`, the CLI automatically fetches OHLCV from **yfinance** for the config date range and **caches** them to CSV for subsequent runs. Delete the CSV files to force a refresh.

### Outputs (per run)

- `results.json` — summary metrics (Sharpe, Sortino, max drawdown, hit rate, etc.).
- `trades.csv` — every simulated fill (timestamp, ticker, side, quantity, price, value, pnl_gbp).
- `equity_curve.csv` — date and portfolio value.
- `run_metadata.json` — config hash, seed, timestamp.

See **Walk-Forward Validation** for multi-fold runs and the promotion report.

---

## How it benefits this project

1. **Quantitative release gate**  
   Strategy or risk changes can be required to pass a backtest and walk-forward check (e.g. Sharpe above a threshold, drawdown and hit rate within bounds) before going live.

2. **Calibration and tuning**  
   Once we have backtest and live results, we can compare recent backtest windows to actual outcomes to calibrate conviction, sizing, and strategy weights (e.g. US-2.1, US-2.2 in the roadmap).

3. **Scenario and regime analysis**  
   Scenario configs (bull, bear, sideways) and different date windows show how the strategy behaves in different regimes, supporting regime-aware improvements (e.g. US-3.2).

4. **Transparency and audit**  
   Every run is reproducible (seed + config), and artefacts are stored so we can audit what was tested before a deployment.

5. **Future extensions**  
   The same engine can later plug in **reused sub-strategy logic** (momentum, mean reversion, factor) and **risk rules** from the live pipeline for closer alignment between backtest and production.

---

## References

- Implementation plan: [BACKTESTING_PROJECT_PLAN.md](BACKTESTING_PROJECT_PLAN.md)
- Walk-forward and promotion report: [WALK_FORWARD_VALIDATION.md](WALK_FORWARD_VALIDATION.md)
- Roadmap: [SOPHISTICATION_ROADMAP.md](SOPHISTICATION_ROADMAP.md) (US-5.1, US-5.2)
