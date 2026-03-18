---
tags: [investment-agent, orders, execution, stop-loss, trailing]
status: active
last_updated: 2026-03-18
---

# Order Management and Execution

Post-trade order lifecycle: initial stop-loss, ATR-based reassessment, trailing stops, and limit dip-buy orders. All adjustments audited and gated by config switches.

## Order Types

- **Market orders** — BUY, SELL, REDUCE via T212 market order API
- **Stop-loss (GTC)** — automatically placed after every BUY using Claude's `stop_loss_pct`. Default -8% if no decision-level pct.
- **Trailing stops** — software-based: high-water mark tracked per position, stop ratchets up to HWM × (1 - trail_pct/100). Cancel + replace (T212 has no native trailing stop). Gated by min_profit_pct: 10% — only activates when position is sufficiently in profit.
- **Limit dip-buy** — when strategy outputs `entry_type: "limit_dip"`, places limit BUY at current_price × (1 - offset_pct/100) instead of market order.

## Execution Flow

1. **Before SELL/REDUCE:** cancel conflicting stop-loss orders (T212 reserves shares for pending stops). If cancellation fails, SELL is aborted. For `liquidate_all()`, cancellation is fail-open.
2. **After BUY:** place GTC stop-loss. Optimistic placement — placed even when order status is "pending" (market BUYs may fill shortly).
3. **Each cycle post-execution:**
   - `place_missing_stops()` — covers positions without a pending stop
   - `reassess_stops()` — ATR-based: 14-day ATR × multiplier, clamped to [3%, 15%]. Only tightens by default. Skip if change < 0.5%.
   - `apply_trailing_stops()` — HWM ratchet for positions in profit ≥ 10%

## Guardrails

- **£500 order floor** — BUY, REDUCE, and limit paths require minimum order value. Explicit market SELL and protective stop-loss are exempt so small holdings can be exited/protected.
- **REDUCE floor safeguard** — if REDUCE would leave position below £500, auto-converts to full SELL.
- **Reduction tiers** — REDUCE rounded to nearest tier (25%, 50%, 70%, 100%). Below 25% skipped unless residual floor triggers.
- **Order dedup** — 5-minute window prevents double execution.
- **Ticker normalisation** — plain symbols (e.g. "AAPL") auto-mapped to T212 instrument IDs ("AAPL_US_EQ") before execution.
- **Execution retry** — 2 retries with 5s backoff for transient T212 failures.

## Order Status

Derived from T212 API: FILLED/PARTIALLY_FILLED → filled, NEW/CONFIRMED → pending, REJECTED/CANCELLED → failed. Don't assume filled on 200 OK. At cycle start, `sync_order_status_from_t212()` reconciles pending → filled.

Pending semantics: MARKET + pending = accepted but not yet executed (common outside market hours). STOP + pending = working protective order, expected to stay pending for days.

## ATR-Based Reassessment

New stop = current_price - (14d ATR × atr_multiplier). Clamped to [min_stop_distance_pct, max_stop_distance_pct]. By default only tightens (never widens). Skip if change < 0.5% to avoid churn. Cancel existing T212 stop, place new one, record in stop_loss_adjustments.

## Future Candidates

- Take-profit orders (limit sell at target %)
- Per-ticker trailing/reassess overrides
- Chained OCO-style behaviour
- Backtesting alignment for stop/limit fills

## Related Notes

- [[Multi-LLM Pipeline Architecture]]
- [[Risk and Governance Framework]]
- [[Project Overview]]
