---
title: Order Management
tags: [order-management, stop-loss, trailing, limit-orders]
status: active
last_updated: 2026-03-30
user_stories: [US-3.5]
related: [GOVERNANCE.md]
---

# Order Management

> Stop-loss, trailing stops, limit dip-buy orders, and the lean execution-quality / fill-recovery slice.

## Purpose

Manage post-trade order lifecycle — initial stop-loss placement, ATR-based reassessment, tiered profit-lock floors, software trailing stops, and limit dip-buy orders. All adjustments are audited and gated by config switches. Autonomous exits are intentionally slower than entries: BUY remains active, while ordinary SELL and REDUCE actions are profit-gated upstream before order management executes them.

## Scope

Order management covers:

1. **Initial stop-loss** — GTC stop placed after every BUY using Claude's `stop_loss_pct`.
2. **ATR-based stop reassessment** — Recalculate stop levels each cycle from 14-day ATR; cancel/replace when changed.
3. **Tiered profit-lock floors** — When unrealized gain crosses configured thresholds, enforce a minimum locked-profit stop floor.
4. **Trailing stops** — Software-based: high-water mark (HWM), stop at `HWM × (1 - trail_pct/100)`; cancel + replace (T212 has no native trailing stop).
5. **Limit dip-buy orders** — When strategy outputs `entry_type: "limit_dip"`, place limit BUY below current price instead of market.
6. **Execution-quality telemetry** — For market orders, persist decision price, realised average fill price, fill/remainder quantities, and side-adjusted slippage in basis points.
7. **Partial-fill recovery** — Preserve unfilled market-order remainder and allow one conservative BUY-only retry when a later approved cycle still covers it.

All adjustments are persisted to `stop_loss_adjustments` and (where applicable) emitted as `order_adjustment` Slack notifications. Feature is gated by `order_management.enabled`; each sub-feature has its own switch.

---

## Current Design

### Pipeline integration

- **Before SELL/REDUCE execution:** `OrderManager.execute_market_order()` calls `cancel_conflicting_stops(ticker)` to cancel any pending stop-loss orders for the ticker before placing the market SELL/REDUCE. T212 reserves shares for pending stop orders, so attempting a SELL without cancelling the stop first causes T212 to reject the order. If cancellation fails (and it's not a 404/already-gone), the SELL is aborted. For `liquidate_all()`, stop cancellation is fail-open (attempt SELL regardless). After a REDUCE, `place_missing_stops()` in the same cycle places a new stop for the remaining shares.
- **Newer HOLD/QUEUED decision after an earlier pending SELL:** On live cycles, the orchestrator calls `cancel_pending_market_sells(ticker, reason)` before recording the `strategy_hold` / `strategy_queued` rejection path. This cancels any still-live pending broker market SELL for the ticker and marks the local `orders` row `cancelled`, preventing stale pre-open exits from surviving a newer strategy view.
- **After BUY execution:** Orchestrator calls `OrderManager.place_stop_loss(ticker, quantity, current_price, stop_loss_pct)` when `exec_result.status` in (filled, dry_run). Pending market BUYs are **not** given an immediate stop because T212 rejects stop placement before the position exists; they are covered by the next cycle's `place_missing_stops()` once the BUY fills. Stop price = `current_price × (1 + stop_loss_pct/100)` (e.g. -15% → 85% of price). The T212 API expects `timeValidity: "GOOD_TILL_CANCEL"` (not `"GTC"`); `T212Client` maps config/caller values accordingly.
- **Place missing stops:** Before reassessment each cycle, `StopLossManager.place_missing_stops(positions, stocks_data)` places stops for positions without one, using `default_stop_loss_pct` (or ATR-based when available).
- **BUY path (market vs limit):** For each approved BUY, orchestrator reads `decision.entry_type` (default `"market"`). If `"limit_dip"`, it calls `StopLossManager.place_limit_buy(...)` with `target_amount_gbp`, `current_price`, and optional `offset_pct`; otherwise executes market order as today. Autonomous BUY sizing enforces the £500 minimum ticket, prefers whole-share quantities with a small overspend tolerance, and only falls back to fractional shares when a whole-share order cannot satisfy policy.
- **Autonomous exit policy upstream of order placement:** Ordinary SELL decisions are blocked unless the position is up at least `sell_min_profit_pct` (default `15%`) and the strategy marks the exit as `gain_realization`, or the exit is explicitly tagged `hard_exit`. REDUCE is reserved for rare profit trims only: only `25%` or `50%` trims survive orchestration, and only once the relevant profit thresholds have been reached.
- **Post-execution (same cycle):** After all trades, orchestrator calls:
  - `StopLossManager.place_missing_stops(positions, stocks_data, cycle_id)` — Place stops for positions without one.
  - `StopLossManager.reassess_stops(positions, stocks_data, cycle_id)` — ATR-based stop levels for all positions; only tighten if `only_tighten_stops` is true.
  - `StopLossManager.apply_trailing_stops(positions, cycle_id)` — HWM-based ratchet; cancel existing stop, place new one at trail distance below HWM.
- **Execution retry:** Mutating T212 POST/DELETE requests are not automatically retried. Only safe GET requests use retry logic.
- **Execution-quality slice (delivered 2026-03-29):** Live market orders are written with `decision_price`, `filled_quantity`, `remaining_quantity`, and `price=None` until broker sync or immediate execution data provides a realised fill. `slippage_bps` is side-adjusted so positive numbers mean worse execution for the operator. Dry-run market orders log zero slippage and no remainder. Stop and limit orders intentionally do not participate in this telemetry slice.
- **Partial-fill resubmission (delivered 2026-03-29):** `sync_orders_with_t212()` records partial fills from Trading 212 history. If a market BUY is partially filled and the live remainder later disappears, the order is marked `cancelled` while preserving the already-filled quantity and the remainder. One later approved BUY cycle may retry the exact remainder once, using a tagged dedup key and `strategy="partial_fill_resubmit"`. Direct/manual orders (`slack_direct`), SELL/REDUCE orders, and recursive retry chains are intentionally excluded.
- **T212 empty-body DELETE:** T212's `DELETE /equity/orders/{id}` returns HTTP 200 with an empty body. `T212Client._request` returns `{}` for empty responses. The retry predicate only retries 429/5xx/network errors; 4xx (including 404) fails immediately. `cancel_conflicting_stops` also unwraps tenacity `RetryError` to detect 404 in the underlying exception.

### ATR-based reassessment

- For each position: get 14-day ATR from `stocks_data` (indicators).
- New stop = `current_price - (ATR × atr_multiplier)`; clamp to `[min_stop_distance_pct, max_stop_distance_pct]` below current price.
- If `only_tighten_stops` is true, skip when new stop would be lower (wider) than existing.
- Skip if change &lt; 0.5% to avoid churn.
- Cancel existing T212 stop (if any), place new stop; record in `stop_loss_adjustments`.

### Trailing stops

- HWM per ticker from latest `StopLossAdjustment` with `adjustment_type="trailing"` or from current price if first time.
- When current price &gt; HWM, update HWM and set new stop = `HWM × (1 - trail_pct/100)`; **cancel old stop first, then place new one**. T212 only allows one pending stop per instrument — placing a second stop while the first is still active is rejected by T212. If the new stop placement fails after the old is cancelled, an emergency stop at the old price is immediately re-placed to restore protection.
- **Guard:** If the computed new stop ≥ current price (price has fallen below HWM-stop level), the ratchet is skipped and recorded as `status=skipped, trigger_reason=trailing_ratchet_invalid`.
- **Min profit gate:** Trailing stops are gated by `min_profit_pct: 20` — trailing only activates when the position is in profit by at least 20%. When enabled (`trailing_stops.enabled: true`), positions below this threshold do not get trailing adjustments.

### Tiered profit-lock floors

- Tier floors are configured under `order_management.profit_lock_tiers` as `{unrealized_gain_pct, min_lock_pct}` rules.
- At each cycle, StopLossManager derives the currently applicable tier by selecting the highest threshold less than or equal to the position's unrealized gain.
- Tier floor stop price is `current_price × (1 - min_lock_pct/100)`.
- Reassessment and trailing both enforce tier floors by taking the tighter protective stop.
- Effective floor precedence: `max(atr_stop, tier_floor, profit_lock_required_stop)` where applicable.

### Limit dip-buy

- Limit price = `current_price × (1 - offset_pct/100)` (default from config).
- Quantity from `target_amount_gbp / limit_price` (floored). Time validity from config (`DAY` or `GTC`).
- Order logged in `orders`; adjustment in `stop_loss_adjustments` with `adjustment_type="limit_order"`, `trigger_reason="limit_dip"`.

### Data model

- **Order** — All orders (market, limit, stop); `order_type` = market | limit | stop.
- **StopLossAdjustment** — `ticker`, `cycle_id`, `adjustment_type` (reassess | trailing | limit_order), `old_stop_price`, `new_stop_price`, `current_price`, `high_water_mark`, `atr_value`, `tier_gain_trigger_pct`, `tier_min_lock_pct`, `tier_rule_label`, `trigger_reason`, `t212_cancelled_order_id`, `t212_new_order_id`, `status`.

---

## Configuration (`config/settings.yaml`)

```yaml
order_management:
  enabled: true
  default_stop_loss_pct: -12   # Used when placing missing stops (no ATR or no decision)
  reassess_stops: true
  trailing_stops:
    enabled: true
    default_trail_pct: 10.0
    min_profit_pct: 20   # Trailing only activates when position is in profit by at least 20%
  profit_lock_tiers:
    enabled: true
    tiers:
      - { unrealized_gain_pct: 5.0, min_lock_pct: 2.0 }
      - { unrealized_gain_pct: 8.0, min_lock_pct: 5.0 }
      - { unrealized_gain_pct: 15.0, min_lock_pct: 10.0 }
      - { unrealized_gain_pct: 25.0, min_lock_pct: 15.0 }
      - { unrealized_gain_pct: 50.0, min_lock_pct: 25.0 }
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
| `trailing_stops.min_profit_pct` | Gate: trailing only activates when position profit ≥ this % (default 20). |
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
| Trailing stops | Yes | On | `trailing_stops.enabled: true`; gated by `min_profit_pct: 20`. |
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

The Order Management page shows: **Order Health** (unresolved failed count, local-vs-live pending counts, stale/reconciled pending counts, last reconciliation timestamp), **Execution Quality** (recent market-order slippage summaries, BUY-vs-EXIT grouped charting, and open partial-fill visibility), **Recent Orders** (all market/stop orders with status: filled/pending/dry_run/failed plus failure detail drill-down and market-order decision/fill/slippage/remainder columns), **Current Stop-Loss Levels** (per position, source: order or adjustment), and **Adjustment History** (ATR reassessment, trailing, limit orders). Order status reflects T212 API response (see rule 7 in CLAUDE.md).

Clarification on `pending`:
- `MARKET` + `pending` usually means the order is accepted (`NEW`) but not yet executed; this is common outside market hours.
- `STOP` + `pending` is expected for working protective stops; these remain open until the stop price is triggered, cancelled, or replaced.
- Local market-order truth is reconciled by `OrderManager.sync_orders_with_t212()`. PARTIALLY_FILLED remains `pending` while the live remainder still exists; if that remainder disappears, the order is marked `cancelled` while keeping `filled_quantity` and `remaining_quantity` for audit and optional later retry.
- Dashboard `/api/orders/health` runs reconciliation on demand: stale local `pending` stop rows that are missing from live T212 pending orders are marked `cancelled` with an audit message.
- Failed-order alerting is based on unresolved failures (not raw historical failed rows). A failure remains unresolved if it is recent (default 7 days) or if no later successful order exists for the same `ticker + action + order_type`.

## Related Notes

- [Architecture](ARCHITECTURE.md) — Order Manager and Stop-Loss Manager in pipeline
- [Governance](GOVERNANCE.md) — §3.3 Intelligent Order Management, dedup, audit
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md)
