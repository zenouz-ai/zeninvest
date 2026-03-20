# Trading System Production Audit

**Date:** 2026-03-19
**Scope:** Full codebase audit covering execution, risk, data layer, LLM pipeline, notifications, testing, and operational resilience.
**Auditor:** Claude Opus 4.6 (automated deep audit)

---

## Executive Summary

The system is well-architected with defense-in-depth (Strategy → Moderation → Risk → Execution), fail-open notifications, and comprehensive logging. However, several **critical financial-risk issues** exist in the execution layer that could cause real-money loss or inconsistent state in production. The risk layer has two permanently disabled rules. The LLM moderation pipeline defaults to AGREE on parse failure.

**Total findings:** 34 (3 Critical, 6 High, 12 Medium, 13 Low)

---

## Critical Findings

### C-1: Tenacity retries on POST can duplicate real-money orders
**File:** `src/agents/execution/t212_client.py:86`
**Severity:** CRITICAL

`_request()` uses `@retry(stop=stop_after_attempt(3))` for ALL HTTP methods, including POST to `/equity/orders/market`. If the first attempt succeeds but the response is lost (e.g., timeout reading response body), the retry places a **second real order**. T212 does not support idempotency keys. The dedup layer in OrderManager is quantity-based with a 5-minute window, but a retry happens within seconds — if the first attempt's DB record wasn't written (see C-2), the dedup won't catch it.

**Recommendation:** Exempt mutating methods (POST, DELETE) from automatic retry, or implement a client-side idempotency mechanism (e.g., store a UUID before the request, check it on retry).

### C-2: Order placed on T212 but DB record may not be written
**File:** `src/agents/execution/order_manager.py:429-444`
**Severity:** CRITICAL

The T212 order is placed first (line 429), then the DB record is written (line 444). If the process crashes between these two lines, real money is spent but no local record exists. The dedup check won't catch a retry since no Order row was written. Same pattern exists for stop-loss placement (`place_stop_loss`).

**Recommendation:** Write a "pending" DB record *before* the T212 API call, then update it with the T212 response. This ensures crash recovery can detect orphaned orders.

### C-3: `liquidate_all` hardcodes `status="filled"` without checking T212 response
**File:** `src/agents/execution/order_manager.py:742`
**Severity:** CRITICAL

During HALT (the most critical state), `liquidate_all` places market sell orders and immediately records them as "filled" without inspecting the T212 response status. If the order is REJECTED or remains pending, the system believes positions are closed when they are not.

**Recommendation:** Apply the same T212 status mapping used in `execute_market_order` (lines 433-442).

---

## High Findings

### H-1: Cancel-then-replace stop-loss is not atomic
**File:** `src/agents/execution/stop_loss_manager.py:424-441`
**Severity:** HIGH

In `_replace_stop`, the old stop is cancelled (line 428) then a new one is placed (line 435). If the new placement fails, the position is left **unprotected** with no stop-loss. No retry or alert is raised. Additionally, if the cancel itself fails (line 431), execution continues to place a new stop — potentially creating **two active stops** for the same position.

**Recommendation:** Reverse the order: place the new stop first, then cancel the old one. Or implement a "stop pending replacement" state.

### H-2: Portfolio data stale throughout cycle — risk of over-allocation
**File:** `src/orchestrator/main.py:285-294`
**Severity:** HIGH

`portfolio_data` (cash, positions, total value) is fetched once at cycle start. All subsequent BUY orders use this same snapshot for allocation calculations. After the first BUY executes, actual cash is reduced, but subsequent BUYs still see the original cash — multiple BUYs can claim the same cash pool, exceeding the cash floor.

**Recommendation:** Refresh cash balance after each BUY execution, or track a running "committed cash" total within the cycle.

### H-3: Correlation check permanently disabled
**File:** `src/orchestrator/main.py:678`
**Severity:** HIGH

`portfolio_returns={}` is always passed to `RiskManager.evaluate_trade()`. The correlation check (risk_manager.py lines 106-111) always returns "Not enough positions" — the rule provides **zero protection** in production. A documented risk rule is silently doing nothing.

### H-4: Daily loss halt permanently disabled
**File:** `src/orchestrator/main.py:1091`
**Severity:** HIGH

`daily_pnl_pct` is hardcoded to `0.0` in `_get_portfolio_data()`. The `check_daily_loss_halt` rule (risk_manager.py lines 240-266) can never trigger since `0.0 < -max_loss` is always false. Another permanently disabled safety mechanism.

### H-5: GPT-4o defaults to AGREE on JSON parse failure
**File:** `src/agents/moderation/openai_mod.py:143-151`
**Severity:** HIGH

When GPT-4o returns invalid JSON, the fallback returns `"verdict": "AGREE"`. A malformed LLM response becomes a silent approval vote. If GPT-4o consistently returns garbage (model change, API issue), all trades get rubber-stamped.

**Recommendation:** Default to `"DISAGREE"` or `"ABSTAIN"` on parse failure, or require at least one moderator to produce a valid parsed response.

### H-6: Session leaks in orchestrator and scheduler
**Files:** `src/orchestrator/main.py:136-150`, `src/scheduler/scheduler.py:62-75, 107-124, 150-167`
**Severity:** HIGH

Multiple locations use `session.close()` outside a `finally` block. If `session.commit()` raises, the session is never closed. In the long-running scheduler process, this will gradually exhaust the connection pool.

**Recommendation:** Move all `session.close()` calls into `finally` blocks.

---

## Medium Findings

### M-1: Dedup check is not atomic with order placement
**File:** `src/agents/execution/order_manager.py:61-77`

`_is_duplicate` runs a SELECT, then execution continues separately. Two concurrent cycles (manual + scheduled) could both pass dedup for the same ticker before either writes an Order row.

### M-2: Failed stop cancel still places new stop — duplicate stops possible
**File:** `src/agents/execution/stop_loss_manager.py:431-432`

If the cancel fails (exception caught as warning), a new stop is placed anyway, resulting in two active stops for the same position.

### M-3: DB audit record failures swallowed — trades execute without audit trail
**Files:** Multiple locations across `order_manager.py`, `risk_manager.py`, `stop_loss_manager.py`

All DB write failures for order records, risk decisions, and stop-loss adjustments are caught and logged but execution proceeds. The audit trail can have gaps with no alerting.

### M-4: `dry_run` stops returned as "pending" in DB fallback
**File:** `src/agents/execution/stop_loss_manager.py:503`

`_get_pending_stops_from_db` includes `Order.status.in_(["pending", "dry_run"])`. When switching from dry-run to live mode, stale dry-run records appear as real pending stops.

### M-5: No response body validation on T212 API
**File:** `src/agents/execution/t212_client.py:123-124`

If T212 returns 200 with empty/non-JSON body, `response.json()` raises `JSONDecodeError` — which triggers tenacity retry, potentially re-placing a market order (see C-1).

### M-6: Rate limit check is not thread-safe
**File:** `src/agents/execution/t212_client.py:49-53`

`_rate_remaining` is a plain instance variable with no locking. Concurrent requests could both pass the rate check.

### M-7: No timeout on entire cycle
**File:** `src/orchestrator/main.py`

`run_cycle()` has no overall timeout. A hanging LLM call blocks the cycle indefinitely. The scheduler may queue the next cycle while the current one is stuck.

### M-8: Exception re-raised after notification can lose original error
**File:** `src/orchestrator/main.py:1002-1019`

After catching an exception, the code emits notifications and then re-raises. If the notification itself throws, the original exception is lost.

### M-9: Notification retry blocks main thread
**File:** `src/agents/notifications/service.py:297`

`time.sleep()` in the retry loop can add up to 4 seconds of blocking per failed channel per event.

### M-10: Missing rollback in cost_tracker.log_cost()
**File:** `src/utils/cost_tracker.py:97-116`

No `except` block with `session.rollback()`. Relies on implicit rollback on close.

### M-11: HALTED liquidation returns before fetching portfolio data
**File:** `src/orchestrator/main.py:277-282`

The HALTED early-return happens before `portfolio_data` is fetched. The cycle summary notification has no content about what was liquidated.

### M-12: Test fixture dual-database isolation leak
**File:** `tests/` (multiple files)

Each test file creates its own in-memory engine, while the root conftest also sets up a global in-memory engine. If any code path calls `get_session()` from the real `database.py` instead of the patched version, it hits a different (potentially empty) database rather than failing loudly.

---

## Low Findings

### L-1: Execution continues after order failure — journal created for failed trades
**File:** `src/orchestrator/main.py:1396-1407`

### L-2: `value_gbp` uses stale caller-provided price, not execution price
**File:** `src/agents/execution/order_manager.py:314`

### L-3: No dedup on stop-loss placement
**File:** `src/agents/execution/stop_loss_manager.py`

Unlike market orders, stop placements have no dedup window. Scheduler overlap could create duplicate stops.

### L-4: SELL actions skip most risk checks (by design but worth noting)
**File:** `src/agents/risk/risk_manager.py:458-480`

`check_min_positions` could block selling a losing position when at minimum portfolio size.

### L-5: HWM resets if StopLossAdjustment records are deleted
**File:** `src/agents/execution/stop_loss_manager.py:519-535`

Trailing stop high-water marks are persisted in DB records. Clearing the table drops all HWMs to current price.

### L-6: Dashboard event logging failures silently swallowed with `pass`
**File:** `src/agents/execution/order_manager.py:185-186`

### L-7: API call logging failure is swallowed
**File:** `src/agents/execution/t212_client.py:80-83`

### L-8: Gemini moderator also defaults to AGREE on all parse failures
**File:** `src/agents/moderation/gemini_mod.py:339-410`

After multiple repair attempts, falls back to AGREE.

### L-9: `sync_order_status_from_t212` opens a new session per order
**File:** `src/agents/execution/order_manager.py:517-579`

No locking; concurrent sync calls could double-update.

### L-10: Dependency pinning uses floor pins only
**File:** `pyproject.toml`

Uses `>=` for nearly all dependencies. `poetry.lock` pins exact versions, but `poetry update` could pull breaking changes. No `pip-audit` or `safety` in CI.

### L-11: No shared test conftest in `tests/` directory
**File:** `tests/` (30 files)

Every test file independently defines `db_session` and `mock_get_session` fixtures, leading to duplication and inconsistent patching depth.

### L-12: Performance metric model mismatch
**File:** `src/orchestrator/main.py` references `PerformanceMetric.metric_name` but model uses `snapshot_date` with individual columns.

### L-13: Correlation check returns `passed=True` on any exception
**File:** `src/agents/risk/risk_manager.py:148-154`

NumPy errors cause the trade to be approved. Combined with H-3, this rule is doubly ineffective.

---

## Positive Findings

The audit also identified well-implemented patterns:

1. **Defense in depth** — 4-layer pipeline (Strategy → Moderation → Risk → Execution) is consistently enforced
2. **Fail-open notifications** — notification failures never block trade execution
3. **T212 status mapping** — `execute_market_order` correctly maps T212 statuses instead of assuming filled (except `liquidate_all`)
4. **Cost degradation** — graceful budget degradation with clear state transitions
5. **Dedup mechanism** — 5-minute window for market orders prevents most double-execution
6. **Risk VETO is final** — no LLM involvement in risk decisions; deterministic rules
7. **Order sync** — periodic sync with T212 corrects local status for pending orders
8. **WAL mode** — SQLite configured with WAL for better concurrent read performance
9. **In-memory test isolation** — tests never touch the production database
10. **Comprehensive logging** — structured logging throughout with Rich formatting

---

## Remediation Status

### Phase 1 (Completed — 2026-03-19)
| ID | Status | Fix |
|----|--------|-----|
| **C-1** | FIXED | Split `_request` into safe (GET, retried) and unsafe (POST/DELETE, no retry) |
| **C-2** | FIXED | Write-before-execute: "submitting" DB record before T212 API call |
| **C-3** | FIXED | `liquidate_all` now maps T212 response status properly |
| **H-1** | FIXED | Reversed stop replacement: new stop placed first, old cancelled after |
| **H-5** | FIXED | Moderator parse-failure default changed to DISAGREE (GPT-4o + Gemini) |
| **H-6** | FIXED | Session leaks fixed with proper `finally` blocks in orchestrator + scheduler |

### Phase 2 (Completed — 2026-03-20)
| ID | Status | Fix |
|----|--------|-----|
| **H-2** | FIXED | Track `committed_cash` within cycle; BUYs see reduced cash; cash floor guard |
| **H-3** | FIXED | `_get_portfolio_returns()` computes return series from OHLCV for correlation check |
| **H-4** | FIXED | `daily_pnl_pct` computed from latest PortfolioSnapshot vs current total_value |
| **M-7** | FIXED | Cycle-level timeout via `signal.alarm` (default 30min, configurable) |
| **M-8** | FIXED | Notification/summary wrapped in try/except; original exception never lost |
| **M-11** | FIXED | HALTED path fetches portfolio data before liquidation for meaningful alerts |

### Remaining (Backlog)
| ID | Severity | Description |
|----|----------|-------------|
| M-1 | Medium | Dedup check not atomic with order placement |
| M-2 | Medium | Failed stop cancel still places new stop (duplicate stops) |
| M-3 | Medium | DB audit record failures swallowed |
| M-4 | Medium | `dry_run` stops in DB fallback |
| M-5 | Medium | No response body validation on T212 API |
| M-6 | Medium | Rate limit check not thread-safe |
| M-9 | Medium | Notification retry blocks main thread |
| M-10 | Medium | Missing rollback in cost_tracker.log_cost() |
| M-12 | Medium | Test fixture dual-database isolation leak |
| L-1..L-13 | Low | Various minor issues (see findings above) |
