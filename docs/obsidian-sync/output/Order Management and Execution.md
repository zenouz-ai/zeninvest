---
tags: [investment-agent, orders, execution, stop-loss, trailing]
status: active
last_updated: 2026-03-29
---

# Order Management and Execution

Post-trade order lifecycle: initial stop-loss, ATR-based reassessment, trailing stops, and limit dip-buy orders. All adjustments audited and gated by config switches. BUY remains active, while ordinary SELL and REDUCE decisions are intentionally slowed down by upstream profit gates.

## Order Types

- **Market orders** — BUY, SELL, REDUCE via T212 market order API
- **Stop-loss (GTC)** — automatically placed after every BUY using Claude's `stop_loss_pct`. Default -15% if no decision-level pct.
- **Trailing stops** — software-based: high-water mark tracked per position, stop ratchets up to HWM × (1 - trail_pct/100). Cancel + replace (T212 has no native trailing stop). Gated by `min_profit_pct: 20%` so trailing only activates once the position is meaningfully in profit.
- **Limit dip-buy** — when strategy outputs `entry_type: "limit_dip"`, places limit BUY at current_price × (1 - offset_pct/100) instead of market order.

## Execution Flow

1. **Write-before-execute** — live market orders are recorded with status "submitting" before the T212 API call. If the process crashes mid-call, the order record still exists for reconciliation.
2. **No retry on POST/DELETE** — mutating T212 requests are never automatically retried (T212 has no idempotency keys). A single `place_market_order` call is issued. Only safe methods (GET) are retried. This prevents double-submission on timeout.
3. **Before SELL/REDUCE:** cancel conflicting stop-loss orders (T212 reserves shares for pending stops). If cancellation fails, SELL is aborted. For `liquidate_all()`, cancellation is fail-open.
4. **After BUY:** place GTC stop-loss. Optimistic placement — placed even when order status is "pending" (market BUYs may fill shortly).
5. **BUY sizing:** autonomous BUYs enforce the £500 minimum ticket, prefer whole-share quantities with a small overspend tolerance, and only fall back to fractional shares when a whole-share order cannot satisfy policy.
4. **Each cycle post-execution:**
   - `place_missing_stops()` — covers positions without a pending stop
   - `reassess_stops()` — ATR-based: 14-day ATR × multiplier, clamped to [3%, 15%]. Only tightens by default. Skip if change < 0.5%.
   - `apply_trailing_stops()` — HWM ratchet for positions in profit ≥ 20%

## Guardrails

- **£500 order floor** — BUY, REDUCE, and limit paths require minimum order value. For MARKET BUYs, the floor check uses the target trade value and then prefers whole-share sizing before fractional fallback. Explicit market SELL and protective stop-loss are exempt so small holdings can be exited/protected.
- **REDUCE floor safeguard** — if REDUCE would leave position below £500, auto-converts to full SELL.
- **Slow SELL policy** — ordinary autonomous SELL is blocked below 15% unrealized profit unless the exit is a `hard_exit`. Profit-taking SELLs must be tagged `gain_realization`.
- **Reduction tiers** — REDUCE is restricted to 25% or 50% profit trims only. REDUCE 25% requires at least 25% unrealized profit, and REDUCE 50% requires at least 40%.
- **Order dedup** — 5-minute window prevents double execution.
- **Ticker normalisation** — plain symbols (e.g. "AAPL") auto-mapped to T212 instrument IDs ("AAPL_US_EQ") before execution.
- **Execution retry** — 2 retries with 5s backoff for transient T212 failures.

## Execution Quality Telemetry (US-7.3)

Every order now tracks:
- **decision_price** — price at the moment strategy decided to act
- **filled_quantity** and **remaining_quantity** — partial fill visibility
- **slippage_bps** — side-adjusted so positive always means worse execution for the operator (BUY: fill > decision, SELL: fill < decision)
- **price** field is treated as realised average fill price for live orders (null until fill is confirmed)

Dashboard surfaces execution quality: decision/fill/slippage/remainder columns plus open partial-fill visibility.

## Partial Fill Recovery (US-7.2)

Conservative approach: if a BUY partially fills and the live remainder disappears (broker-cancelled), the order is marked "cancelled" while preserving filled and remaining quantities. One later approved BUY cycle may retry the exact stored remainder, but only for autonomous/strategy-driven market BUYs — never for direct/manual orders.

## Order Status

Derived from T212 API: FILLED/PARTIALLY_FILLED → filled, NEW/CONFIRMED → pending, REJECTED/CANCELLED → failed. Don't assume filled on 200 OK. At cycle start, `sync_orders_with_t212()` reconciles pending → filled, updates fill telemetry, and reconciles stale local rows.

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
