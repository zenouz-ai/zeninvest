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

- **After BUY execution:** Orchestrator calls `OrderManager.place_stop_loss(ticker, quantity, current_price, stop_loss_pct)` → T212 `POST /equity/orders/stop` (GTC). Stop price = `current_price × (1 + stop_loss_pct/100)` (e.g. -8% → 92% of price). The T212 API expects `timeValidity: "GOOD_TILL_CANCEL"` (not `"GTC"`); `T212Client` maps config/caller values accordingly.
- **BUY path (market vs limit):** For each approved BUY, orchestrator reads `decision.entry_type` (default `"market"`). If `"limit_dip"`, it calls `StopLossManager.place_limit_buy(...)` with `target_amount_gbp`, `current_price`, and optional `offset_pct`; otherwise executes market order as today.
- **Post-execution (same cycle):** After all trades, orchestrator calls:
  - `StopLossManager.reassess_stops(positions, stocks_data, cycle_id)` — ATR-based stop levels for all positions; only tighten if `only_tighten_stops` is true.
  - `StopLossManager.apply_trailing_stops(positions, cycle_id)` — HWM-based ratchet; cancel existing stop, place new one at trail distance below HWM.

### ATR-based reassessment

- For each position: get 14-day ATR from `stocks_data` (indicators).
- New stop = `current_price - (ATR × atr_multiplier)`; clamp to `[min_stop_distance_pct, max_stop_distance_pct]` below current price.
- If `only_tighten_stops` is true, skip when new stop would be lower (wider) than existing.
- Skip if change &lt; 0.5% to avoid churn.
- Cancel existing T212 stop (if any), place new stop; record in `stop_loss_adjustments`.

### Trailing stops

- HWM per ticker from latest `StopLossAdjustment` with `adjustment_type="trailing"` or from current price if first time.
- When current price &gt; HWM, update HWM and set new stop = `HWM × (1 - trail_pct/100)`; cancel old stop, place new one.

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
  reassess_stops: true
  trailing_stops:
    enabled: false
    default_trail_pct: 5.0
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
| `trailing_stops.enabled` | Software trailing stops (HWM ratchet). |
| `trailing_stops.default_trail_pct` | Trail distance % below HWM. |
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
| Trailing stops | Yes | Off | `trailing_stops.enabled: false` — enable when desired. |
| Limit dip-buy | Yes | On | `limit_orders.enabled: true`; strategy must output `entry_type: "limit_dip"` to use. |

---

## Future Sophistication (Roadmap Candidates)

These are **not** yet committed user stories; they are candidate enhancements for the roadmap.

- **Take-profit orders** — Limit sell at target % above entry (e.g. Claude's `upside_target_pct`). Would require T212 limit sell and lifecycle (cancel when stop hits first, or time-based expiry).
- **Per-ticker trailing / reassess overrides** — Config or strategy output to disable trailing or reassessment for specific tickers.
- **Chained OCO-style behaviour** — e.g. “cancel limit buy when stop sell is hit” (if T212 or execution layer supports it).
- **Backtesting alignment** — Paper broker and backtesting engine to model stop-loss and limit order fills (e.g. next-bar stop hit, limit fill when price touches) for consistency with live behaviour.

When a future user story is adopted, add it to `docs/SOPHISTICATION_ROADMAP.md` with acceptance criteria and link back to this doc.

## Related Notes

- [Architecture](ARCHITECTURE.md) — Order Manager and Stop-Loss Manager in pipeline
- [Governance](GOVERNANCE.md) — §3.3 Intelligent Order Management, dedup, audit
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md)
