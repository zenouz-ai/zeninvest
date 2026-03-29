---
tags: [investment-agent, risk, governance, security]
status: active
last_updated: 2026-03-29
---

# Risk and Governance Framework

The system's safety architecture. Risk rules are deterministic Python — no LLM can override, modify, or bypass them. Their VETO is final.

## Core Principle: Defense in Depth

Every trade passes through 5 layers. No single component has unchecked authority:

1. **Strategy (Claude)** — proposes trades with conviction scores
2. **Moderation (GPT-4o + Gemini)** — can BLOCK via consensus
3. **Risk (deterministic Python)** — can REJECT or RESIZE, **never overridden by LLMs**
4. **Opportunity (UOV)** — ranks/queues approved BUYs only
5. **Execution (T212 client)** — dedup + rate limiting

## The 11 Hard Rules

| # | Rule | Threshold |
|---|------|-----------|
| 1 | Max single stock | ≤ 15% of portfolio |
| 2 | Max sector concentration | ≤ 35% |
| 3 | Correlation limit | Portfolio avg pairwise < 0.7 |
| 4 | Drawdown state machine | >30% → CAUTIOUS, >40% → HALTED (liquidate all) |
| 5 | VIX-based position limits | VIX >25: max 8%; VIX >35: max 5% |
| 6 | Daily loss halt | >2% daily loss → no new buys for 24h |
| 7 | Cash floor | Always ≥ 10% cash |
| 8 | Min positions | ≥ 5 once invested (prevents over-concentration) |
| 9 | Min holding period | No REDUCE/SELL within 24h unless over max stock/sector |
| 10 | Cautious state guard | CAUTIOUS: no new BUYs, only SELL/REDUCE/HOLD |
| 11 | System halted | HALTED: all trading suspended |

Why these can't be overridden: `RiskManager` imports only numpy, json, dataclasses, and config. No LLM SDK. Pure mathematical comparisons. Sequential gate — every trade passes through `evaluate_trade()` after moderation, before execution.

## State Machine

- **ACTIVE** — normal operation, full risk budget, max 15% per position
- **CAUTIOUS** — triggered at configurable drawdown (default 30%). No new positions. Max 8% per position. Auto-recovers when drawdown drops below threshold, or manual `--reset-peak`.
- **HALTED** — triggered at 40% drawdown. Liquidate ALL positions. Alert operator. Auto-recovers after 3 consecutive clean live cycles (US-7.5); otherwise manual intervention required to resume.
- **Practice mode** — state machine relaxed, always stays ACTIVE. Drawdown logged but never triggers transitions.
- **Peak inflation detection** (US-7.5) — detects artificially inflated peak values (e.g. from deposits) that would trigger false drawdown. Prevents spurious CAUTIOUS/HALTED transitions.

## Cost Controls

Daily budgets: Anthropic £1, OpenAI £0.75, Google £0.50. Monthly cap £50. At ~$3–7/month actual spend, this is well within limits.

Degradation chain: FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED. Each moderator self-checks its budget before every call.

## Human Oversight

- Practice/Demo mode by default — switching to live is a major deployment decision
- Pause/Resume control persisted in DB, survives restarts
- Force sell: `--force-sell <TICKER>` bypasses normal pipeline
- Scheduled execution only — no autonomous intraday reactions
- Daily reports (21:30 UTC) and weekly reports (Fri 22:00)

## Security

- All API keys from env vars, never hardcoded, never logged, never in LLM prompts
- Key rotation: 90-day cycle for LLM/trading keys, 180-day for data providers
- Structured JSON output enforcement — LLMs can't inject arbitrary instructions
- Input sanitisation: all LLM inputs are system-sourced numeric/structured data, no user free text
- Even if an LLM were fully compromised, it could only *propose* trades that still must pass deterministic risk checks

## Execution Quality and Fill Telemetry

- **Write-before-execute** — orders recorded with status "submitting" before the broker API call, so no fill is ever lost even on crash
- **Execution quality telemetry** (US-7.3) — tracks decision_price, filled_quantity, remaining_quantity, and slippage_bps (side-adjusted: positive = worse for operator)
- **Partial fill recovery** (US-7.2) — conservative: one later approved BUY cycle may retry the exact stored remainder, but only for autonomous/strategy-driven market BUYs, never for direct/manual orders
- **No retry on POST/DELETE** — mutating T212 requests are never automatically retried (no idempotency keys). Only GET is retried.
- **Off-hours order warnings** (US-7.5) — orders placed outside market hours carry an annotation so operators know execution may be delayed

## Database Integrity

- **CHECK constraints** (US-7.5) — database-level invariants on critical columns (quantities, percentages, scores) so invalid data cannot be persisted even if application logic has a bug

## Fail-Safe Defaults

- Unknown state → ACTIVE with no positions
- LLM call fails → trade skipped
- T212 unreachable → cycle terminates
- Budget exceeded → graceful degradation
- Notification failure → never blocks trade execution (fail-open)
- Order dedup: 5-minute window prevents double execution

## Audit Trail

Every decision is logged to SQLite: strategy_decisions, moderation_logs, risk_decisions, orders, cost_logs, api_logs, research_logs, notification_logs, portfolio_snapshots, stop_loss_adjustments, events_log, runs. Full reproducibility.

## Related Notes

- [[Multi-LLM Pipeline Architecture]]
- [[Order Management and Execution]]
- [[Project Overview]]
