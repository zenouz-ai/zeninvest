---
tags: [investment-agent, architecture, pipeline, multi-llm]
status: active
last_updated: 2026-03-18
---

# Multi-LLM Pipeline Architecture

The core insight: no single LLM should have unchecked authority over real money. Every trade passes through 4 independent layers — Strategy proposes, Moderation challenges, Risk vetoes, Execution deduplicates.

## Pipeline Flow

1. **Data Fetcher** — yfinance (OHLCV + fundamentals), Finnhub (analyst recs, insider sentiment), Alpha Vantage (per-ticker news sentiment, broad market, sector performance). Macro intelligence: S&P 500 sector performance + economic headlines. When intraday mode, Finnhub/AV are deferred to active-review tickers only. Web search fallback (Brave/Tavily) when Finnhub or AV times out.

2. **Universe Screener** — sector-balanced, cap-tiered candidate discovery. ~6900 US equities from T212 seed. 70/20/10% large/mid/small cap. Review vs new buckets (50/50 target). Configurable cooldown. Runs every cycle regardless of state.

3. **Strategy Engine** — three sub-strategies (Momentum 35%, Mean Reversion 30%, Factor 35%) produce rule-based scores. Claude Sonnet synthesises them with company profiles, news sentiment, analyst data, and portfolio state into BUY/SELL/HOLD/REDUCE/QUEUED decisions with conviction scores. When research is enabled, Strategy has a tool-use loop with 5 search tools (capped at 20 calls).

4. **Moderation Panel** — GPT-4o (skeptic) and Gemini Flash (risk assessor) independently review each proposed trade. Both receive full market context + Claude's market thesis to challenge. When research is enabled, both moderators also have tool-use loops (Skeptic: 8 calls, Risk: 7 calls). Consensus logic: 3/3 AGREE → APPROVED, 2/3 → CAUTION, 2+ DISAGREE → BLOCKED.

5. **Risk Manager** — 11 deterministic Python rules with VETO power. Never calls an LLM. Architecturally isolated. Checks: max stock/sector %, correlation, drawdown state, VIX limits, daily loss halt, cash floor, min positions, min holding period, cautious guard.

6. **Opportunity Optimizer (UOV)** — cross-cycle scoring: uov_raw → uov_z → uov_final → uov_ewma. In active mode, ranks approved BUYs by EWMA, executes top, queues rest. Emits swap suggestions but never triggers SELL.

7. **Execution** — market orders, stop-loss (GTC), trailing stops, limit dip-buy. 5-min dedup window. Order status reconciled from T212 each cycle. Cancel conflicting stops before SELL/REDUCE.

8. **Journal & Reporting** — per-trade markdown journals, daily snapshots (21:30 UTC), weekly reports (Fri 22:00).

## State Machine

ACTIVE → CAUTIOUS (>30% drawdown) → HALTED (>40%, liquidate all). Recovery from HALTED requires manual intervention. Practice mode: state machine relaxed, always stays ACTIVE.

## Cost Degradation

FULL → NO_GEMINI (Google over budget) → NO_GPT4O (both moderators over budget) → NO_STRATEGY (Anthropic over budget) → HALTED (monthly cap hit). Each moderator self-checks its own budget before every call.

## Moderation Consensus

- 3/3 AGREE → APPROVED (proceed normally)
- 2/3 AGREE → CAUTION (proceed with flag)
- 2+ DISAGREE or HIGH_RISK + DISAGREE → BLOCKED
- Fallback (1 mod): AGREE + conviction ≥ 75 → APPROVED
- Fallback (0 mods): conviction ≥ 85 → APPROVED, else BLOCKED

## Dashboard

FastAPI REST API + SSE stream (Phase 1 + Phase 1.5). 8 frontend pages: Home (state badge, dry/live run buttons, P&L, activity feed), Universe (sortable, expandable with full committee reasoning), Run History, Portfolio, Opportunity Pipeline, Order Management, Costs, Roadmap. ZENOUZ.ai brand. Reads agent SQLite directly — no duplicate tables.

## Architectural Decisions

- **2026-02-26** — Enriched moderator data: GPT-4o and Gemini now receive identical full market context (indicators, fundamentals, macro, sub-strategy signals, analyst data, news). Previously they only got Finnhub JSON + truncated news.
- **2026-02-27** — Added Claude's market_assessment to moderator context. Moderators now challenge the overall thesis, not just individual trades.
- **2026-03-06** — Added macro intelligence: sector performance (AV SECTOR, yfinance SPDR fallback) and economic headlines (Finnhub /news) feed strategy and moderation.
- **2026-03-13** — Agentic research: all 3 committee members can search the web mid-reasoning. Shared pipeline-wide budget enforcement (35 calls/cycle max).

## Related Notes

- [[Project Overview]]
- [[Risk and Governance Framework]]
- [[Data Pipeline Rationale]]
- [[Sophistication Roadmap]]
