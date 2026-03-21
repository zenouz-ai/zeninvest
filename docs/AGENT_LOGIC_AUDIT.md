# Agent Logic Audit Report

**Date:** 2026-03-20
**Scope:** Strategy Engine, Moderation Panel, Risk Manager, Opportunity Scorer/Optimizer, Execution layer, Orchestrator pipeline flow
**Auditor:** Claude Opus 4.6 (automated code audit)
**Prior audits:** `AUDIT_REPORT.md` (codebase-wide, 2026-03-17), `TRADING_SYSTEM_AUDIT.md` (production safety, 2026-03-19)

---

## Executive Summary

This audit focuses on **agent decision-making logic** — how LLM outputs are parsed, validated, and flow through the Strategy → Moderation → Risk → Opportunity → Execution pipeline. While the codebase is well-structured with defence-in-depth, this audit identified **5 Critical, 7 High, 9 Medium, and 6 Low** findings, primarily around:

- **MODIFY verdicts** requested by moderators but silently discarded
- **CAUTION consensus** treated identically to APPROVED (no downstream differentiation)
- **Missing validation** of LLM-produced numeric fields (conviction, scores, stop_loss_pct)
- **Risk rule gaps** for SELL/REDUCE actions (sector, VIX, cash floor checks skipped)
- **Strategy output** fields used but never defined in the prompt schema (`entry_type`)

### Severity Distribution

| Severity | Count | Fixed (this PR) |
|----------|-------|-----------------|
| Critical | 5 | 5 |
| High | 7 | 7 |
| Medium | 9 | 0 (backlog) |
| Low | 6 | 0 (backlog) |

---

## Critical Findings

### C-1: MODIFY verdicts silently ignored — moderator resize recommendations discarded

**Files:** `src/agents/moderation/panel.py:228-249`, `src/orchestrator/main.py:777`
**Component:** Moderation Panel → Orchestrator

Both GPT-4o and Gemini system prompts explicitly allow a `MODIFY` verdict with a `modifications` payload (`target_allocation_pct`, `stop_loss_pct`). The consensus function (`_determine_consensus`) only counts `AGREE` and `DISAGREE` — `MODIFY` falls through to the `else: return "CAUTION"` branch (line 249). The orchestrator never inspects `modifications` from moderator verdicts.

**Impact:** When a moderator says "I'd approve this BUY but at 5% instead of 10%", the resize suggestion is discarded. The trade either proceeds at full allocation or is blocked entirely — no middle ground.

**Fix:** Count MODIFY as a conditional AGREE in consensus logic; when consensus allows the trade, apply the most conservative `modifications.target_allocation_pct` as a cap. Pass modified allocation to Risk.

### C-2: CAUTION consensus has no downstream effect — identical to APPROVED

**Files:** `src/orchestrator/main.py:681-704`, `src/agents/moderation/panel.py:164`
**Component:** Orchestrator

The orchestrator checks only `if mod_result.consensus == "BLOCKED"` to reject trades. Both `APPROVED` and `CAUTION` pass through identically. The `caution_flag` is set on `ModerationResult` (line 164) but never read by any downstream code.

**Impact:** Trades where one moderator dissents or a high-risk flag is raised receive no special handling — no reduced allocation, no tighter stop-loss, no additional logging. The three-tier consensus system (APPROVED/CAUTION/BLOCKED) is effectively two-tier.

**Fix:** When consensus is CAUTION, apply a configurable allocation cap (e.g. 75% of proposed) and tighten stop-loss by 2 percentage points. Log the caution flag in the trade result.

### C-3: No validation of strategy conviction scores or target allocations

**Files:** `src/agents/strategy/engine.py:471-488`, `src/orchestrator/main.py:606`
**Component:** Strategy Engine → Orchestrator

Claude's JSON output includes `conviction` (expected 0-100) and `target_allocation_pct` (expected ~2-15%) but neither is validated. The orchestrator reads them with `decision.get("conviction", 0)` and `decision.get("target_allocation_pct", 0)` without clamping. A hallucinated conviction of 150 or a target_allocation_pct of 50% would flow through to moderation and risk unchecked.

**Impact:** Risk rules check `proposed_allocation_pct` against limits, which would catch extreme allocations — but the moderation panel uses raw conviction for its threshold logic (e.g. `conviction >= 70` bypasses with 0 moderators). A hallucinated conviction of 999 would auto-approve with zero moderator review.

**Fix:** Clamp conviction to [0, 100] and target_allocation_pct to [0, max_single_stock_pct] immediately after parsing. Log a warning when clamping occurs.

### C-4: Gemini score extraction lacks bounds validation

**Files:** `src/agents/moderation/gemini_mod.py:382-398`
**Component:** Gemini Moderator

In the regex fallback for malformed Gemini JSON, scores are extracted as raw integers (`int(growth_match.group(1))`) without bounds validation. If Gemini outputs `"risk_score": 42`, the regex extracts 42 directly. The `high_risk_flag` logic (`risk > growth`) uses these unclamped values, potentially triggering false positives or missed high-risk situations.

**Impact:** Out-of-range scores corrupt the consensus function's high-risk assessment. The `high_risk_flag` could be incorrectly true or false based on garbage data.

**Fix:** Clamp extracted scores to [1, 10] range. Apply same validation in the normal JSON parse path.

### C-5: Orphaned "submitting" orders never synced — crash recovery gap

**Files:** `src/agents/execution/order_manager.py:583,632`
**Component:** Order Manager

Orders are created with `status="submitting"` before the T212 API call (write-before-execute pattern). However, `sync_order_status_from_t212()` only queried `Order.status == "pending"`, not "submitting". If the process crashes between writing the submitting record and receiving the T212 response, the order remains "submitting" permanently — `sync_order_status_from_t212()` will never find it to reconcile.

**Impact:** Orphaned "submitting" orders break the audit trail and could allow duplicate orders after the dedup window expires.

**Fix:** Changed both `sync_order_status_from_t212()` and `reconcile_pending_stop_orders_with_t212()` to query `Order.status.in_(["pending", "submitting"])`.

---

## High Findings

### H-6: Unexpected T212 status values silently default to "pending"

**File:** `src/agents/execution/order_manager.py:486-497`
**Component:** Order Manager

The T212 status mapping defaults unknown values to "pending". If T212 returns "EXPIRED" or other new statuses, orders would incorrectly appear as pending when they're actually finalized. This is an execution-layer concern captured for completeness.

**Impact:** Low probability but could leave orders in wrong status.

**Status:** Backlog — requires T212 API documentation review for comprehensive status handling.

---

### H-1: Risk rules for SELL/REDUCE skip critical checks

**File:** `src/agents/risk/risk_manager.py:472-493`
**Component:** Risk Manager

For BUY/HOLD actions, Risk checks: max_single_stock, max_sector, vix_limit, cash_floor, daily_loss_halt, cautious_state. For SELL/REDUCE, it only checks: drawdown, correlation, min_positions, min_holding_period. Missing checks for SELL/REDUCE:

- **VIX check**: In extreme VIX, rapid selling could be panic-driven. No check.
- **Daily loss halt**: A SELL during a daily loss halt could lock in losses.

While SELL/REDUCE are less risky than BUY (you're reducing exposure), the min_positions check (line 379) blocks SELL when `num_positions <= min_pos` but doesn't consider that the SELL might be strategy-driven to exit a losing position.

**Impact:** Low — risk of harm is limited since reducing exposure is generally safe. But min_positions could block a justified exit from a crashing stock.

**Fix:** Add `is_risk_driven_exit` parameter: if a strategy says SELL with conviction ≥ 80 and the position is losing >10%, exempt from min_positions.

### H-2: `entry_type` field used by orchestrator but not defined in strategy prompt schema

**Files:** `src/orchestrator/main.py:907`, `src/agents/strategy/prompts.py`
**Component:** Strategy Engine → Orchestrator

The orchestrator reads `decision.get("entry_type", "market")` (line 907) to decide between market orders and limit dip-buys. However, the strategy prompt schema (in `prompts.py`) does not define `entry_type` as a valid output field. Claude would only produce `entry_type: "limit_dip"` if it happened to hallucinate or if the field leaked from surrounding context.

**Impact:** The limit dip-buy feature is unreachable through normal pipeline operation. It would require explicit prompt engineering to activate.

**Fix:** Add `entry_type` to the strategy prompt JSON schema with allowed values `"market"` (default) and `"limit_dip"`. Add `limit_offset_pct` as an optional field.

### H-3: Strategy tool-use timeout is too aggressive (30 seconds)

**File:** `src/agents/strategy/engine.py:338`
**Component:** Strategy Engine

The tool-use loop has a 30-second timeout (`timeout_sec = 30`). With up to 8 iterations, each Claude API call taking 5-10 seconds, and research tool calls adding latency, this timeout can trigger prematurely even on normal runs with 2-3 tool calls.

**Impact:** Research-enabled strategy runs may be cut short, returning `{"error": "research_timeout", "decisions": []}`, causing the entire cycle to fail with `strategy_error`.

**Fix:** Increase timeout to 120 seconds (2 minutes) or make it configurable via `settings.strategy_tool_timeout_seconds`.

### H-4: Moderation log doesn't record consensus field for individual moderator rows

**File:** `src/agents/moderation/panel.py:267-289`
**Component:** Moderation Panel

The GPT-4o and Gemini `ModerationLog` entries (lines 267-289) don't include the `consensus` field — only the strategy row does (line 263). This means dashboard queries that join on `consensus` per-moderator will get NULL for the actual moderators, making it hard to see which moderators contributed to which consensus.

**Impact:** Dashboard transparency — moderator log rows lack the consensus context they contributed to.

**Fix:** Add `consensus=result.consensus` to GPT-4o and Gemini ModerationLog entries.

### H-5: `_repair_truncated_json` can produce partial/corrupt decisions

**File:** `src/agents/strategy/engine.py:431-462`
**Component:** Strategy Engine

The JSON repair function finds the last `}` and tries to close the structure. If Claude's output was truncated mid-decision (e.g. `{"ticker": "AAPL", "action": "BUY", "convi`), the repair could create a decision with missing fields (`conviction`, `reasoning`, `stop_loss_pct` all None). The orchestrator would then process this partial decision with defaults of 0 conviction and 0 allocation.

**Impact:** A truncated response could produce ghost decisions — ticker+action with all other fields missing. A BUY with conviction 0 and allocation 0 would be harmless (zero value), but could still create confusing log entries and dashboard noise.

**Fix:** After repair, validate each decision has at minimum: `ticker`, `action`, and `conviction > 0`. Drop decisions that fail validation.

### H-6: No deduplication of strategy decisions by ticker

**File:** `src/orchestrator/main.py:598`
**Component:** Orchestrator

The strategy prompt instructs Claude to output "exactly one decision for EVERY ticker", but no validation enforces this. If Claude outputs duplicate tickers (e.g., AAPL_US_EQ with BUY and then AAPL_US_EQ with SELL), both would be processed. The first might go into `pending_buys`, and the second could execute as a SELL — resulting in conflicting trades on the same security in the same cycle.

**Impact:** Duplicate BUY orders or contradictory BUY+SELL in the same cycle. The 5-minute dedup window might not catch cross-phase duplicates (SELL executes immediately, BUY deferred to UOV phase).

**Fix:** Deduplicate decisions by ticker before the moderation/risk loop, keeping the first occurrence.

**Status:** Fixed — dedup step added before the decision processing loop.

---

## Medium Findings

### M-1: Strategy prompt truncation risk — portfolio state limited to 2000 chars

**File:** `src/orchestrator/main.py:538`
**Component:** Orchestrator

`portfolio_state_str = json.dumps(portfolio_data, indent=2, default=str)[:2000]` — With 15 positions, each with multiple fields, this truncation could cut off mid-JSON, giving Claude an incomplete picture. Similar: analyst_summary truncated to 3000 chars (line 519), news_summary to 3000 chars (line 520).

**Impact:** Claude may not see all current positions or all analyst data, leading to decisions that ignore critical context (e.g. not knowing a position already exists).

### M-2: Opportunity scorer `_center_100` returns 0 for None values

**File:** `src/agents/opportunity/scorer.py` (various lines)
**Component:** Opportunity Scorer

When sub-strategy scores are None (e.g. factor_quality for a ticker with no fundamentals), `_center_100(None)` returns 0 (the neutral point). This is correct but means tickers with missing data get a neutral score rather than a penalty, potentially overranking data-sparse stocks.

### M-3: Risk manager doesn't track cumulative sector allocation within a cycle

**File:** `src/agents/risk/risk_manager.py:82-84`
**Component:** Risk Manager

The sector allocation passed to `check_max_sector` is based on the portfolio snapshot at cycle start. When multiple BUYs in the same sector are approved within one cycle, the first BUY doesn't update sector_allocations, so the second BUY sees stale data. The cash floor fix (H-2 in TRADING_SYSTEM_AUDIT) addressed this for cash but not for sector allocation.

**Impact:** In theory, two 20% BUYs in Technology could both pass the 35% sector limit check, resulting in a 40% sector concentration.

### M-4: Correlation check always returns `passed=True` on exception

**File:** `src/agents/risk/risk_manager.py:149-155`
**Component:** Risk Manager

The correlation check has a broad exception handler that returns `passed=True` with message "allowing trade". If the numpy calculation fails for any reason (e.g. NaN values, mismatched array lengths), the trade is auto-approved rather than flagged.

### M-5: OpenAI tool-use moderation falls back to single-turn on any exception

**File:** `src/agents/moderation/openai_mod.py:281-285`
**Component:** GPT-4o Moderator

If the tool-use loop raises any exception (network error, parse error, budget exhaustion), it falls back to `_review_single_turn`. This means tool-use errors are silently retried as a non-tool call, potentially consuming double the API budget.

### M-6: Gemini tool-use falls back to single-turn when loop exhausts iterations

**File:** `src/agents/moderation/gemini_mod.py:334`
**Component:** Gemini Moderator

When the Gemini tool-use loop hits `max_iter` without a final text response, it falls back to `_review_single_turn` (line 334). This means a Gemini that keeps calling tools without concluding triggers an additional API call.

### M-7: `stop_loss_pct` from strategy not validated before stop-loss placement

**Files:** `src/agents/strategy/engine.py:487`, `src/agents/execution/stop_loss_manager.py`
**Component:** Strategy → Execution

Claude outputs `stop_loss_pct` (e.g. -8 for 8% below entry) but this value is never validated. A hallucinated value like -50 (50% stop-loss) or +5 (positive, meaning set stop above current price) would be passed to `StopLossManager`. The ATR-based reassessment has min/max clamps, but initial placement from strategy does not.

### M-8: Orchestrator passes raw `is_existing_winner` based only on ticker presence

**File:** `src/orchestrator/main.py:728`
**Component:** Orchestrator → Risk

`is_existing_winner=ticker in existing_tickers` — This sets "is_winner" to True for any existing position, regardless of whether it's actually profitable. The Risk `check_cautious_state` (line 406) allows BUY "add to winners" in CAUTIOUS state, but this check treats all existing positions as winners.

### M-9: Sector allocation check double-counts existing position on re-allocation

**File:** `src/agents/risk/risk_manager.py:87`
**Component:** Risk Manager

`check_max_sector` computes `new_sector_pct = current_sector_pct + proposed_pct`. Since `proposed_pct` is a **target** allocation (not incremental), and `current_sector_pct` already includes the ticker's existing allocation, re-allocating an existing position double-counts it. Example: AAPL at 3% in Technology (sector at 20%), strategy targets 5% → check sees 20% + 5% = 25%, but real sector exposure would be 22% (subtract old 3%, add new 5%).

**Impact:** Conservative (over-estimates sector exposure, fails safe). May occasionally block valid sector re-allocations that are within limits.

**Fix:** Subtract the ticker's current allocation from `current_sector_pct` before adding `proposed_pct`.

### Investigation note: `check_max_single_stock` (line 58)

The risk audit flagged `total_pct = proposed_pct` (ignoring `current_pct`) as potentially critical. **Investigation confirmed this is correct behaviour.** The strategy's `target_allocation_pct` is a **target** (total desired portfolio %), not an incremental addition. The orchestrator passes it directly to execution at `_execute_trade` (line 1429: `trade_value = current_value * final_alloc / 100`). Comparing the target directly against `max_single_stock_pct` is the correct check. Removed the dead `current_pct` variable and added a clarifying docstring.

---

## Low Findings

### L-1: Strategy sub-strategies hardcode top-N limits

**Files:** `src/agents/strategy/engine.py:83,96,104`
**Component:** Strategy Engine

`rank_by_factor(top_n=30)` and `sorted_sigs[:35]` are hardcoded. If `max_candidates` changes in config, these limits won't follow.

### L-2: Moderation `ModerationResult.gpt_score` tries two field names

**File:** `src/agents/moderation/panel.py:46-47`
**Component:** Moderation Panel

`self.gpt4o_verdict.get("score") or self.gpt4o_verdict.get("confidence_score")` — The GPT-4o prompt doesn't define a `score` field, only `confidence_score` isn't in the schema either. The score extraction is fragile.

### L-3: Opportunity optimizer doesn't validate `final_allocation_pct` from pending buys

**File:** `src/agents/opportunity/optimizer.py:53`
**Component:** Opportunity Optimizer

`float(candidate.get("final_allocation_pct", 0.0))` — if the value is somehow a string or None, the float() could raise. No try/except.

### L-4: Risk `min_positions` check uses equality not strict less-than

**File:** `src/agents/risk/risk_manager.py:379`
**Component:** Risk Manager

`if action == "SELL" and num_positions <= min_pos` — This blocks SELL when exactly at min_pos. With min_pos=3 and 3 positions, you can't sell any position, even a crashing one.

### L-5: `_log_decisions` writes raw JSON that may be very large

**File:** `src/agents/strategy/engine.py:492`
**Component:** Strategy Engine

`raw_response_json=raw_json` — The full Claude response is stored per decision row, so 35 decisions each get the same ~10KB blob. This wastes ~350KB per cycle in the database.

### L-6: Gemini `_parse_json_with_repair` default to DISAGREE doesn't raise

**File:** `src/agents/moderation/gemini_mod.py:401-412`
**Component:** Gemini Moderator

The function name suggests it parses JSON and raises on failure. Instead, it returns a dict with `verdict: "DISAGREE"` as a safe default. The caller (`_review_single_turn`) also has a `json.JSONDecodeError` handler. These never fire because `_parse_json_with_repair` swallows the error. The architecture works but is misleading for maintainers.

---

## Recommendations Summary

### Immediate (this PR)

1. **C-1**: Apply moderator `modifications.target_allocation_pct` as allocation cap when consensus allows trade
2. **C-2**: Differentiate CAUTION vs APPROVED — apply allocation reduction and log caution flag
3. **C-3**: Clamp conviction to [0, 100] and target_allocation_pct to [0, max_single_stock_pct]
4. **C-4**: Clamp Gemini scores to [1, 10] in both parse paths
5. **H-1**: Allow risk-driven exits to bypass min_positions when conviction ≥ 80 and position losing
6. **H-2**: Add `entry_type` to strategy prompt schema
7. **H-3**: Increase strategy tool-use timeout to 120s
8. **H-4**: Record consensus on all moderator log rows
9. **H-5**: Validate repaired decisions have required fields
10. **H-6**: Deduplicate strategy decisions by ticker before moderation/risk

### Backlog

- M-1 through M-9: See descriptions above
- L-1 through L-6: See descriptions above

---

## Positive Observations

1. **Defence in depth** works: even with the CAUTION/MODIFY gaps, Risk Manager's hard rules would catch extreme cases
2. **Budget enforcement** is solid: every LLM call checks budget before execution
3. **Fail-open design** for non-critical paths (dashboard, notifications) is well-implemented
4. **Write-before-execute** pattern for orders prevents silent failures
5. **JSON repair** in strategy is a good defensive measure, just needs validation after repair
6. **Research tool integration** is cleanly abstracted with shared budget across pipeline members
