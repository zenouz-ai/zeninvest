# Formal Verification Audit — Investment Agent

> **See also:** [AUDIT_INDEX.md](AUDIT_INDEX.md) (cross-reference), [AUDIT_REPORT.md](AUDIT_REPORT.md) (architectural), [TRADING_SYSTEM_AUDIT.md](TRADING_SYSTEM_AUDIT.md) (execution safety), [AGENT_LOGIC_AUDIT.md](AGENT_LOGIC_AUDIT.md) (LLM pipeline)

**Date:** 2026-03-21
**Scope:** Decision pipeline integrity, state machine, race conditions, invariants, edge cases, crash recovery
**Method:** Systematic audit following formal verification principles — state machines, invariants, proof obligations

---

## Executive Summary

This audit complements the [Agent Logic Audit](AGENT_LOGIC_AUDIT.md) (which focused on LLM output parsing and decision flow) with a formal verification lens: state machine completeness, concurrency safety, invariant enforcement, and crash recovery. The system is well-designed with defence-in-depth, but several structural issues emerge under adversarial timing or edge conditions.

| Severity | Count | Category |
|----------|-------|----------|
| CRITICAL | 3 | Scheduler concurrency, decision deduplication, stop-loss atomicity |
| WARNING | 7 | State machine gaps, race conditions, stale data, DB constraints |
| INFO | 8 | Boundary conditions, design notes |

---

## 1. Decision Pipeline Integrity

### 1.1 CRITICAL: Scheduler allows concurrent cycle execution

**File:** `src/scheduler/scheduler.py:271-280`

APScheduler `add_job()` calls do not set `max_instances=1`. If a cycle hangs (known: Finnhub timeouts on VPS), the next scheduled cycle starts concurrently. Two cycles writing to the same SQLite database causes: lost writes, dedup bypass, state machine races, corrupted snapshots.

**Preconditions:** Cycle takes >4h (intraday) or >12h (standard); Finnhub/AV timeout known to occur.
**Impact:** Database corruption, duplicate orders, state machine race.
**Fix:** Add `max_instances=1` to all analysis cycle jobs.

### 1.2 CRITICAL: Strategy decisions not deduplicated by ticker (FIXED — H-6)

**File:** `src/orchestrator/main.py:594-614`

If Claude outputs the same ticker twice (BUY + SELL), both process through the pipeline — first goes to `pending_buys`, second executes as SELL immediately. Conflicting trades on the same security in the same cycle.

**Status:** Fixed this session. Dedup step added before the moderation/risk loop.

### 1.3 WARNING: Portfolio snapshot frozen for entire cycle

**File:** `src/orchestrator/main.py:291`

Portfolio state is queried once at cycle start and used for all decisions (~10-30 min). If T212 fills a stop-loss during this window, the orchestrator's risk checks use stale position counts. Could approve a BUY for a ticker whose position was just liquidated by stop-loss.

**Preconditions:** Volatile stock triggers stop-loss fill during moderation/risk phase.
**Impact:** Stale capacity count may approve extra BUYs. Mitigated by T212's own limits and next-cycle reconciliation.
**Fix (roadmap):** Re-query portfolio state before BUY execution phase.

### 1.4 INFO: force_sell and liquidate_all bypass pipeline

**File:** `src/orchestrator/main.py:2386-2402, 313`

`force_sell()` calls T212 directly without moderation or risk checks. `liquidate_all()` (HALTED state) does the same. Both are intentional operator emergency actions but represent documented invariant exceptions.

---

## 2. State Machine Analysis

### 2.1 WARNING: HALTED has no automatic recovery path

**File:** `src/orchestrator/state_machine.py:75-103`

HALTED requires manual `--reset-peak`. Even if portfolio recovers above the cautious threshold after liquidation, the system remains HALTED. The peak ratchets upward (never decreases), so a historical peak from a data glitch can trap the system in false HALTED indefinitely.

**Preconditions:** Drawdown >= 40% (live account); portfolio subsequently recovers.
**Impact:** System stays HALTED until operator manually resets. On unattended VPS, this means no trading indefinitely.
**Fix (roadmap):** Add configurable auto-recovery: if drawdown drops below `cautious_drawdown_pct` for N consecutive cycles, transition HALTED → ACTIVE with audit log.

### 2.2 WARNING: PAUSED + HALTED coexist without warning

**File:** `src/orchestrator/state_machine.py:160-172`

`paused` is an independent boolean. Operator can pause a HALTED system, then resume it, forgetting it's HALTED. Next cycle: liquidation proceeds. Dashboard should show compound state (PAUSED+HALTED) and warn on resume.

**Preconditions:** System HALTED; operator pauses then resumes.
**Impact:** Unexpected liquidation on resume. Operator confusion.
**Fix:** Dashboard resume action should check and warn about underlying HALTED state.

### 2.3 INFO: Peak value initialisation is lazy

**File:** `src/orchestrator/state_machine.py:112`, `src/agents/risk/risk_manager.py:196-205`

`peak_portfolio_value` starts NULL. Until first `update_peak()` call, `get_drawdown_state()` returns "ACTIVE" regardless of actual drawdown. First cycle cannot trigger state transitions.

**Preconditions:** Fresh database, first live cycle.
**Impact:** 4-hour window (intraday) where drawdown protection is inactive. Low risk since positions don't exist yet on first cycle.

### 2.4 INFO: State transition is not atomic (TOCTOU)

**File:** `src/orchestrator/main.py:297-349`

State is read at line 297, acted on at line 349. Between read and act, another process (manual CLI, dashboard force-sell) could change state. Current single-threaded scheduler makes this unlikely, but adding `max_instances=1` (Finding 1.1) formally closes the gap.

---

## 3. Race Conditions & Concurrency

### 3.1 CRITICAL: (Same as 1.1) Scheduler has no max_instances guard

This is the single most impactful concurrency bug. All other race conditions become possible only if concurrent cycles run.

### 3.2 WARNING: Cost tracker check-then-act race

**File:** `src/utils/cost_tracker.py:193-245`

`check_budget()` queries SUM(cost_gbp), returns True. Before `log_cost()` writes the new entry, a concurrent call also checks and sees the same sum. Both proceed, exceeding the budget.

**Preconditions:** Concurrent LLM calls (currently impossible in single-threaded model; would manifest if async/parallel research is added).
**Impact:** Daily/monthly budget exceeded by 1 call worth.
**Fix (roadmap):** Atomic check-and-increment via SQL `INSERT ... SELECT WHERE SUM < limit`.

### 3.3 INFO: Order dedup 5-minute boundary

**File:** `src/agents/execution/order_manager.py:56-77`

Dedup uses `>=` on timestamp. At exactly T+5:00.000, the previous order falls outside the window. Not a practical concern (cycles are 4-12h apart), but a theoretical TOCTOU at the boundary.

---

## 4. Invariant Catalogue

These invariants should NEVER be violated. For each, the enforcement mechanism and bypass risk:

| # | Invariant | Enforcement | Bypass Risk |
|---|-----------|-------------|-------------|
| I-1 | No order without Risk Manager approval | `evaluate_trade()` called before `_execute_trade()` | None for normal flow. `force_sell` and `liquidate_all` are documented exceptions. |
| I-2 | Total exposure ≤ (100% - cash_floor_pct) | Risk rule checks `projected_cash < min_cash` (pre-trade) | Stale portfolio snapshot (Finding 1.3) could allow slight over-allocation. |
| I-3 | Single stock ≤ max_single_stock_pct (15%) | Risk rule + allocation clamping (C-3 fix) | Allocation clamped at parsing; risk re-checks before execution. No bypass. |
| I-4 | Single sector ≤ max_sector_pct (35%) | Risk rule checks sector_allocations | Stale sector data if portfolio changes mid-cycle. |
| I-5 | No BUY in CAUTIOUS state | Risk rule: `system_state == "CAUTIOUS"` blocks BUY | No bypass — risk check is mandatory. |
| I-6 | HALTED → liquidate all | `main.py:300-315` triggers `liquidate_all()` | Correct. Stop-loss cancellation is fail-open for liquidation. |
| I-7 | Risk VETO is absolute | No code path executes after risk VETO | Verified: `if risk_verdict.verdict == "REJECT": continue` |
| I-8 | No duplicate orders within 5 minutes | `_is_duplicate()` check before execution | TOCTOU at 5-min boundary (INFO). Concurrent cycles (if 1.1 unfixed) could bypass. |
| I-9 | Moderation consensus required for BUY | Moderation panel runs before risk for BUY/SELL/REDUCE | No bypass in normal flow. Skipped when cost-degraded (NO_GPT4O/NO_GEMINI). |
| I-10 | Cost budget respected | `check_budget()` before each LLM call | TOCTOU if concurrent (Finding 3.2). Single-threaded model is safe. |
| I-11 | Every BUY has a stop-loss | `place_stop_loss()` after BUY; `place_missing_stops()` at cycle start | Crash between BUY and stop creates 4-12h unprotected window (Finding 6.3). |
| I-12 | Queue promotions execute or re-queue | `_update_queue()` commits before execution | Queue deletion before order placement; crash loses ticker (Finding 6.4). |

---

## 5. Edge Cases & Boundary Conditions

### 5.1 WARNING: No market hours check before order placement

**File:** `src/agents/execution/order_manager.py`, `src/scheduler/scheduler.py`

Cycle times are fixed UTC. The system does not verify NYSE is open before placing orders. T212 Practice accepts orders off-hours, but execution quality may differ (wider spreads, deferred fills).

**Impact:** Orders placed during pre-market/after-hours may have poor fill quality.
**Fix (roadmap):** Add `is_market_open()` check; log warning if placing orders off-hours.

### 5.2 INFO: Halted tickers handled gracefully

T212 rejects orders for halted/suspended tickers with HTTP 400/403. The system logs as "failed" and continues. No cascade failure.

### 5.3 INFO: Stock splits handled by T212

T212 manages splits on its side. `get_portfolio()` returns post-split quantities. Stop-loss re-assessment runs each cycle, correcting outdated stops.

### 5.4 INFO: Zero/negative prices guarded

`calculate_quantity()` returns 0 for `price <= 0`. `execute_market_order()` catches `quantity <= 0` and skips. Min order value (£500) prevents tiny orders.

### 5.5 INFO: Cost budget boundary correct

`is_over_daily = daily_spent >= daily_limit` — "at limit" correctly blocks further calls. No off-by-one.

---

## 6. Consistency & Crash Recovery

### 6.1 WARNING: Non-atomic multi-table writes per decision

**File:** `src/orchestrator/main.py:800-870`

A single decision writes to `strategy_decisions`, `moderation_logs`, `risk_decisions`, and `orders` tables in separate sessions/commits. If crash occurs between writes, the decision has partial records. No transaction wraps the full decision lifecycle.

**Preconditions:** Process crash or SIGKILL between commits.
**Impact:** Orphaned records. `StrategyDecision` exists but `Order` missing. Dashboard shows incomplete decision journey. Not financially dangerous (no order = no trade).
**Fix (roadmap):** Wrap decision writes in a single transaction with rollback on failure.

### 6.2 WARNING: Write-before-execute orphans cleaned up (but with delay)

**File:** `src/agents/execution/order_manager.py`

Orders written with `status="submitting"` before T212 API call. If crash between write and T212 response, orphaned "submitting" order persists. Fixed (C-5): `sync_order_status_from_t212()` at cycle start catches these. But there's a 4-12h window where orphan exists.

**Impact:** Dashboard shows phantom pending order until next cycle sync. Low financial risk (T212 never received the order).

### 6.3 CRITICAL: Stop-loss placement not atomic with BUY execution

**File:** `src/orchestrator/main.py:1559-1630`

Market order execution and stop-loss placement are separate operations with separate sessions. If the process crashes after the BUY is filled but before the stop-loss is placed, the position exists on T212 without downside protection. `place_missing_stops()` runs at the start of each cycle and would eventually place the missing stop, but there's a 4-12h window where the position is unprotected.

**Preconditions:** Process crash or T212 API failure between BUY fill and stop-loss placement.
**Impact:** Position vulnerable to unlimited downside for up to one cycle duration.
**Fix (roadmap):** `place_missing_stops()` already mitigates this. Consider adding a `TRADE_WITHOUT_STOP` alert notification when a BUY completes without an accompanying stop.

### 6.4 WARNING: OpportunityQueue deletion committed before order execution

**File:** `src/agents/opportunity/optimizer.py:201-269`, `src/orchestrator/main.py:1026`

When a queued ticker is promoted, the OpportunityQueue row is deleted and committed before the BUY order is placed. If crash occurs between queue commit and order execution, the ticker is silently lost — removed from the queue but never executed.

**Preconditions:** Process crash between optimizer commit and order execution.
**Impact:** Promoted opportunity lost without audit trail. Low probability but violates the principle of atomic state transitions.
**Fix (roadmap):** Add status field to OpportunityQueue (QUEUED → EXECUTING → EXECUTED) and reconcile orphaned EXECUTING rows at cycle start.

### 6.5 WARNING: Minimal database-level constraints

All trading invariants (allocation limits, quantity signs, conviction ranges) are enforced only in Python code. The database has no `CHECK` constraints, no foreign keys linking decisions to orders. If application validation is bypassed (bug, manual DB edit), malformed data can persist.

**Impact:** No safety net beyond application code. Acceptable given thorough test coverage, but worth noting.

### 6.6 INFO: WAL mode enables concurrent reads

`PRAGMA journal_mode=WAL` is set in `database.py`. Dashboard API can read while orchestrator writes without blocking. Reads may see slightly stale data (last committed state), which is acceptable for dashboard display.

---

## Phased Fix Plan

### Phase 1 — This Session (CRITICAL + easy WARNING fixes)

| # | Finding | Fix | Effort |
|---|---------|-----|--------|
| P1-1 | 1.1: Scheduler no max_instances | Add `max_instances=1` to all `add_job()` calls | 5 min |
| P1-2 | 1.2: Decision dedup (H-6) | **DONE** — committed and pushed | — |
| P1-3 | 2.2: PAUSED+HALTED warning | Add log warning when resuming a HALTED system | 10 min |

### Phase 2 — Crash Safety & DB Atomicity (DELIVERED)

| # | Finding | Fix | Status |
|---|---------|-----|--------|
| P2-3 | 6.1: Decision chain integrity | Decision chain integrity check at cycle end: logs orphaned decisions (no trade or rejection record) | **DONE** |
| P2-4 | 1.3: Re-query portfolio before BUY | Refresh portfolio state between SELL/REDUCE and BUY phases (`_get_portfolio_state()` re-called when sells executed) | **DONE** |
| P2-5 | 6.3: BUY without stop-loss alert | `emit_trade_without_stop()` notification when BUY fills but stop-loss placement fails (warning severity, Slack + email) | **DONE** |
| P2-6 | 6.4: OpportunityQueue atomicity | `queue_status` field (QUEUED → EXECUTING → EXECUTED); `_mark_executing()` before orders; `dequeue_executed()` after success; `reconcile_orphaned_executing()` at cycle start | **DONE** |

### Phase 3 — Next Sprint (state machine hardening)

| # | Finding | Fix | Effort |
|---|---------|-----|--------|
| P3-1 | 2.1: HALTED auto-recovery | Add configurable auto-recovery after N cycles below threshold | 2h |
| P3-2 | 5.1: Market hours check | Add `is_market_open()` utility; log warning if off-hours | 1h |

### Phase 4 — Roadmap (hardening for future concurrency)

| # | Finding | Fix | Effort |
|---|---------|-----|--------|
| P4-1 | 3.2: Atomic cost budget | SQL-level check-and-increment for budget enforcement | 2h |
| P4-2 | DB thread safety | Add threading.Lock around session factory if async features added | 1h |
| P4-3 | Peak inflation detection | Warn if peak > 2× recent average; guide operator on reset-peak | 2h |
| P4-4 | Halted ticker denial list | Cache T212 400/403 rejections; skip for 24h | 1h |
| P4-5 | 6.5: DB-level constraints | Add CHECK constraints for quantity signs, conviction range, allocation bounds | 1h |

---

## Invariant Verification Summary

| Invariant | Status | Notes |
|-----------|--------|-------|
| I-1: No order without risk approval | **HOLDS** | force_sell/liquidate_all are documented exceptions |
| I-2: Exposure ≤ budget | **HOLDS** (with caveat) | Stale snapshot can cause slight over-allocation |
| I-3: Single stock ≤ 15% | **HOLDS** | Clamped at parsing + risk check |
| I-4: Sector ≤ 35% | **HOLDS** (with caveat) | Stale sector data possible |
| I-5: No BUY in CAUTIOUS | **HOLDS** | Risk rule enforced |
| I-6: HALTED → liquidate | **HOLDS** | Idempotent |
| I-7: Risk VETO absolute | **HOLDS** | No bypass path found |
| I-8: No duplicate orders | **HOLDS** (with caveat) | 5-min window; concurrent cycles could bypass |
| I-9: Moderation required | **HOLDS** (with caveat) | Skipped under cost degradation (by design) |
| I-10: Cost budget respected | **HOLDS** (single-threaded) | TOCTOU if concurrent |
| I-11: Every BUY has a stop-loss | **HOLDS** (with caveat) | Crash between BUY and stop creates 4-12h gap; `place_missing_stops()` recovers |
| I-12: Queue promotions execute | **WEAK** | Queue deletion committed before execution; crash loses ticker silently |

**Overall Assessment:** The system's core safety invariants hold under normal operation. The primary risk is concurrent cycle execution (Finding 1.1), which could violate I-2, I-8, and I-10. Fix P1-1 (`max_instances=1`) is the highest-priority action. The secondary risk is non-atomic multi-step operations (Findings 6.1, 6.3, 6.4), which could leave partial state on crash — mitigated by next-cycle reconciliation for most cases, but OpportunityQueue (I-12) has no recovery path.
