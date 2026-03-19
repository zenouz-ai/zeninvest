---
tags: [order-management, stop-loss, trailing, limit-orders]
status: delivered
last_updated: 2026-03-10
---

# Order Management

> Stop-loss, trailing stops, and limit dip-buy order lifecycle.

## Purpose

Manage post-trade order lifecycle — initial stop-loss placement, ATR-based reassessment, software trailing stops, and limit dip-buy orders. All adjustments are audited and gated by config switches.

## Scope

Order management covers:

1. **Initial stop-loss** — GTC stop placed after every BUY using Claude's `stop_loss_pct`.
2. **ATR-based stop reassessment** — Recalculate stop levels each cycle from 14-day ATR; cancel/replace when changed.
3. **Trailing stops** — Software-based: high-water mark (HWM), stop at `HWM × (1 - trail_pct/100)`; cancel + replace (T212 has no native trailing stop).
4. **Limit dip-buy orders** — When strategy outputs `entry_type: "limit_dip"`, place limit BUY below current price instead of market.

All adjustments are persisted to `stop_loss_adjustments` and (where applicable) emitted as `order_adjustment` Slack notifications. Feature is gated by `order_management.enabled`; each sub-feature has its own switch.

---

## Current Design

### Pipeline integration

- **Before SELL/REDUCE execution:** `OrderManager.execute_market_order()` calls `cancel_conflicting_stops(ticker)` to cancel any pending stop-loss orders for the ticker before placing the market SELL/REDUCE. T212 reserves shares for pending stop orders, so attempting a SELL without cancelling the stop first causes T212 to reject the order. If cancellation fails (and it's not a 404/already-gone), the SELL is aborted. For `liquidate_all()`, stop cancellation is fail-open (attempt SELL regardless). After a REDUCE, `place_missing_stops()` in the same cycle places a new stop for the remaining shares.
- **After BUY execution:** Orchestrator calls `OrderManager.place_stop_loss(ticker, quantity, current_price, stop_loss_pct)` when `exec_result.status` in (filled, dry_run, **pending**) — optimistic placement for market BUYs. → T212 `POST /equity/orders/stop` (GTC). Stop price = `current_price × (1 + stop_loss_pct/100)` (e.g. -8% → 92% of price). The T212 API expects `timeValidity: "GOOD_TILL_CANCEL"` (not `"GTC"`); `T212Client` maps config/caller values accordingly.
- **Place missing stops:** Before reassessment each cycle, `StopLossManager.place_missing_stops(positions, stocks_data)` places stops for positions without one, using `default_stop_loss_pct` (or ATR-based when available).
- **BUY path (market vs limit):** For each approved BUY, orchestrator reads `decision.entry_type` (default `"market"`). If `"limit_dip"`, it calls `StopLossManager.place_limit_buy(...)` with `target_amount_gbp`, `current_price`, and optional `offset_pct`; otherwise executes market order as today.
- **Post-execution (same cycle):** After all trades, orchestrator calls:
  - `StopLossManager.place_missing_stops(positions, stocks_data, cycle_id)` — Place stops for positions without one.
  - `StopLossManager.reassess_stops(positions, stocks_data, cycle_id)` — ATR-based stop levels for all positions; only tighten if `only_tighten_stops` is true.
  - `StopLossManager.apply_trailing_stops(positions, cycle_id)` — HWM-based ratchet; cancel existing stop, place new one at trail distance below HWM.
- **Execution retry:** T212 order placement and stop operations use 2 retries with 5-second backoff for transient T212 API failures.
- **T212 empty-body DELETE:** T212's `DELETE /equity/orders/{id}` returns HTTP 200 with an empty body. `T212Client._request` returns `{}` for empty responses. The retry predicate only retries 429/5xx/network errors; 4xx (including 404) fails immediately. `cancel_conflicting_stops` also unwraps tenacity `RetryError` to detect 404 in the underlying exception.

### ATR-based reassessment

- For each position: get 14-day ATR from `stocks_data` (indicators).
- New stop = `current_price - (ATR × atr_multiplier)`; clamp to `[min_stop_distance_pct, max_stop_distance_pct]` below current price.
- If `only_tighten_stops` is true, skip when new stop would be lower (wider) than existing.
- Skip if change &lt; 0.5% to avoid churn.
- Cancel existing T212 stop (if any), place new stop; record in `stop_loss_adjustments`.

### Trailing stops

- HWM per ticker from latest `StopLossAdjustment` with `adjustment_type="trailing"` or from current price if first time.
- When current price &gt; HWM, update HWM and set new stop = `HWM × (1 - trail_pct/100)`; cancel old stop, place new one.
- **Min profit gate:** Trailing stops are gated by `min_profit_pct: 10` — trailing only activates when the position is in profit by at least 10%. When enabled (`trailing_stops.enabled: true`), positions below this threshold do not get trailing adjustments.

### Limit dip-buy

- Limit price = `current_price × (1 - offset_pct/100)` (default from config).
- Quantity from `target_amount_gbp / limit_price` (floored). Time validity from config (`DAY` or `GTC`).
- Order logged in `orders`; adjustment in `stop_loss_adjustments` with `adjustment_type="limit_order"`, `trigger_reason="limit_dip"`.

### Data model

- **Order** — All orders (market, limit, stop); `order_type` = market | limit | stop.
- **StopLossAdjustment** — `ticker`, `cycle_id`, `adjustment_type` (reassess | trailing | limit_order), `old_stop_price`, `new_stop_price`, `current_price`, `high_water_mark`, `atr_value`, `trigger_reason`, `t212_cancelled_order_id`, `t212_new_order_id`, `status`.

---

## Configuration (`config/settings.yaml`)

```yaml
order_management:
  enabled: true
  default_stop_loss_pct: -8   # Used when placing missing stops (no ATR or no decision)
  reassess_stops: true
  trailing_stops:
    enabled: true
    default_trail_pct: 5.0
    min_profit_pct: 10   # Trailing only activates when position is in profit by at least 10%
  limit_orders:
    enabled: true
    default_offset_pct: 2.0
    time_validity: GTC
  atr_multiplier: 2.0
  min_stop_distance_pct: 3.0
  max_stop_distance_pct: 15.0
  only_tighten_stops: true
```

| Key | Purpose |
|-----|---------|
| `enabled` | Master switch for order management (reassess, trailing, limit). |
| `reassess_stops` | ATR-based stop reassessment each cycle. |
| `trailing_stops.enabled` | Software trailing stops (HWM ratchet). Now enabled by default. |
| `trailing_stops.default_trail_pct` | Trail distance % below HWM. |
| `trailing_stops.min_profit_pct` | Gate: trailing only activates when position profit ≥ this % (default 10). |
| `limit_orders.enabled` | Allow limit BUYs when strategy outputs `entry_type: "limit_dip"`. |
| `limit_orders.default_offset_pct` | Default % below current price for limit. |
| `limit_orders.time_validity` | DAY or GTC. |
| `atr_multiplier` | ATR × multiplier for volatility-based stop distance. |
| `min_stop_distance_pct` / `max_stop_distance_pct` | Clamp reassessed stops. |
| `only_tighten_stops` | Only move stops up (tighter), never widen. |

---

## Implemented vs Optional

| Feature | Implemented | Default | Notes |
|--------|-------------|---------|--------|
| GTC stop after BUY | Yes | On | Claude's `stop_loss_pct`; no switch (always on when BUY executes). |
| ATR reassessment | Yes | On | `reassess_stops: true`. |
| Trailing stops | Yes | On | `trailing_stops.enabled: true`; gated by `min_profit_pct: 10`. |
| Limit dip-buy | Yes | On | `limit_orders.enabled: true`; strategy must output `entry_type: "limit_dip"` to use. |

---

## Future Sophistication (Roadmap Candidates)

These are **not** yet committed user stories; they are candidate enhancements for the roadmap.

- **Take-profit orders** — Limit sell at target % above entry (e.g. Claude's `upside_target_pct`). Would require T212 limit sell and lifecycle (cancel when stop hits first, or time-based expiry).
- **Per-ticker trailing / reassess overrides** — Config or strategy output to disable trailing or reassessment for specific tickers.
- **Chained OCO-style behaviour** — e.g. “cancel limit buy when stop sell is hit” (if T212 or execution layer supports it).
- **Backtesting alignment** — Paper broker and backtesting engine to model stop-loss and limit order fills (e.g. next-bar stop hit, limit fill when price touches) for consistency with live behaviour.

When a future user story is adopted, add it to `docs/SOPHISTICATION_ROADMAP.md` with acceptance criteria and link back to this doc.

## Dashboard

The Order Management page shows: **Recent Orders** (all market/stop orders with status: filled/pending/dry_run/failed), **Current Stop-Loss Levels** (per position, source: order or adjustment), and **Adjustment History** (ATR reassessment, trailing, limit orders). Order status reflects T212 API response (see rule 7 in CLAUDE.md).

Clarification on `pending`:
- `MARKET` + `pending` usually means the order is accepted (`NEW`) but not yet executed; this is common outside market hours.
- `STOP` + `pending` is expected for working protective stops; these remain open until the stop price is triggered, cancelled, or replaced.
- Local `orders.status` is reconciled at the start of each non-dry-run cycle by `OrderManager.sync_order_status_from_t212()` (pending -> filled when T212 history reports FILLED/PARTIALLY_FILLED).

## Related Notes

- [Architecture](ARCHITECTURE.md) — Order Manager and Stop-Loss Manager in pipeline
- [Governance](GOVERNANCE.md) — §3.3 Intelligent Order Management, dedup, audit
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md)
