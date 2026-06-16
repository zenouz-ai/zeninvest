---
title: Failure Modes & Error Codes
tags: [failures, errors, error-codes, observability, governance]
status: active
last_updated: 2026-06-14
related: [AGENTIC_TRANSFORMATION_PLAN.md, GOVERNANCE.md, ARCHITECTURE.md]
user_stories: [US-9.6]
---

# Failure Modes & Error Codes

> Lightweight taxonomy of how ZenInvest fails, the stable error code for each, how to
> detect it, and how to remediate. Codes live in `src/utils/error_codes.py` (`ErrorCode`)
> and are prefixed onto `logger` messages at real raise/guard sites so incidents are
> greppable (`grep "\[D001\]" logs/`).

This is intentionally a doc + small enum, **not** a registry module or a new exception
hierarchy. Git is the source of truth; promote to a richer module only once codes are
numerous and the dashboard consumes them (see
[AGENTIC_TRANSFORMATION_PLAN.md](AGENTIC_TRANSFORMATION_PLAN.md)).

## Code categories

| Prefix | Domain |
|--------|--------|
| `D` | Data / market-data providers |
| `L` | LLM / committee output |
| `B` | Broker / execution |
| `C` | Concurrency / runtime locks |
| `S` | Security / auth |
| `M` | Model / learning pipeline |
| `P` | Cost / budget ("purse") |

## Catalog

| Code | Trigger | Severity | Detect signal | Remediation | Code site / test |
|------|---------|----------|---------------|-------------|------------------|
| `D001` | Market-data provider API call failed | medium | `[D001]` in logs; `api_logs` error rows | Retry safe reads; fall through enrichment cascade (yfinance → Finnhub → AV → Brave) | `alpha_vantage_client.py`, `finnhub_client.py` |
| `L001` | Model returned non-JSON / wrong shape | medium | `ValueError` "non-object JSON"; moderation log gaps | Normalizer coerces/falls back; trade proceeds with remaining moderators | `openai_mod.py`, `conversation/specialists.py` |
| `B001` | Expected position not held at broker | high | `ValueError` "No position in …" | Reconcile against T212 state; skip SELL | `single_ticker_run.py` |
| `B002` | Execution payload missing / malformed | high | `ValueError` "no prepared execution payload" | Abort execution; re-derive payload | `direct_trade_run.py` |
| `C001` | Another process holds the runtime lock | medium | `RuntimeLockHeldError` with lock metadata | Wait/skip cycle; inspect stale lock file | `runtime/locking.py` |
| `S001` | Required auth secret/config absent | high | `DashboardAuthConfigError` at startup | Set `DASHBOARD_SESSION_SECRET`; fail closed | `dashboard/.../auth.py` |
| `M001` | No trained model artifact available | low | `RuntimeError` "No trained boosters" | Run `cli train`; shadow scoring no-ops | `learning/models/gbm.py` |
| `M002` | Train/score on empty dataset | low | `ValueError` "empty DataFrame" | Rebuild dataset (`cli build`); gate on row count | `learning/models/gbm.py` |
| `P001` | Category/provider daily cap hit | low | `[P001]` warning | Spend resumes next UTC day; raise cap if intentional | `cost_tracker.check_budget` / `check_category_budget` |
| `P002` | Global monthly cap hit; degradation HALTED | high | `[P002]` warning; `DegradationLevel.HALTED` | Halt LLM calls until month rolls over or cap raised | `cost_tracker` |

## Conventions

- Tag at the existing `logger.error`/`logger.warning` site: `logger.error(f"[{ErrorCode.X}] …")`.
- Do not change exception **message** text that tests assert on; tag the log line instead.
- Codes are stable once published — append new codes, never renumber.
