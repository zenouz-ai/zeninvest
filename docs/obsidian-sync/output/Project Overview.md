---
tags: [investment-agent, overview, status]
status: active
last_updated: 2026-03-18
---

# Project Overview

Autonomous investment agent that trades US equities via the Trading 212 Practice API using a multi-LLM pipeline. Built as a personal quant system — innovation, simplicity, elegance, transparency.

## Current Status

**POC v1.0** — deployed to VPS, collecting live performance data on Trading 212 Practice.

- 326 tests passing
- 10 user stories delivered, 22 in pipeline
- Configurable scheduling: 3 intraday cycles (08/12/16 UTC) or 2 standard cycles (07/19 UTC), Mon–Fri
- NYSE market holidays auto-skipped
- Dashboard (Phase 1 + Phase 1.5 Analytics Lite) live on VPS via Docker

## Pipeline at a Glance

```
Orchestrator (3 cycles/day, configurable)
  ├── Market Data     → yfinance + Finnhub + Alpha Vantage
  ├── Universe Screen → Sector-balanced, cap-tiered discovery (~6900 seed)
  ├── Strategy        → Momentum + Mean Rev + Factor → Claude Sonnet synthesis
  ├── Moderation      → GPT-4o (skeptic) + Gemini Flash (risk) → consensus
  ├── Risk            → 11 hard rules, VETO power, never LLM-overridden
  ├── Opportunity     → UOV scoring + ranked BUY queue
  ├── Execution       → T212 API: market + stop-loss + trailing + limit + dedup
  ├── Notifications   → Slack + Email alerts (fail-open)
  └── Journal         → Per-trade journals, daily + weekly reports
```

## Recent Deliveries

- **US-4.4** Agentic Research — all 3 committee members have tool-use loops (5 tools: web, news, sector, SEC EDGAR, macro). Shared pipeline budget. 37 tests.
- **US-1.7** Dashboard — full API + 8 frontend pages (Home, Universe, Run History, Portfolio, Opportunity, Orders, Costs, Roadmap). ZENOUZ.ai brand.
- **US-1.8** Dashboard VPS Deployment — Docker multi-stage build, SPA fallback, accessible at VPS IP:8000.
- **US-5.1** Backtesting Engine — daily replay, paper broker, walk-forward validation, promotion report, yfinance + CSV cache.
- **US-3.5** Intelligent Order Management — ATR-based stops, trailing stops, limit dip-buy.
- **US-3.4** UOV Ranking & Queue — cross-cycle EWMA scoring, BUY ranking, queue + swap suggestions.
- **US-1.5** Chat & Alerts — Slack webhook + SMTP email with persistent audit logging.

## Next Priorities

1. **US-4.5** Proactive Macro News Intelligence — scheduled macro scans, second-order reasoning
2. **US-1.6** Slack NL Trade Commands — "Buy 10 AAPL" via Slack, full pipeline, Risk can still veto
3. **US-1.9** Conversational Trading Workflow — multi-turn session-based chat with confirmation gate
4. **US-2.1 / US-2.2** Conviction Calibration + Dynamic Strategy Weighting — needs ~50 trades
5. **US-7.1** Dashboard Authentication — required before exposing beyond localhost

## Tech Stack

- **Language:** Python 3.11, Poetry
- **LLMs:** Claude Sonnet 4.5 (strategy), GPT-4o (skeptic), Gemini 2.5 Flash (risk)
- **Data:** yfinance, Finnhub, Alpha Vantage, Brave Search, Tavily, SEC EDGAR
- **Execution:** Trading 212 Practice API (httpx)
- **Storage:** SQLite (WAL mode) + Alembic migrations
- **Scheduling:** APScheduler
- **Dashboard:** FastAPI + React (Vite), Docker Compose
- **Infra:** VPS, Docker, Rich logging

## Team

- **Project Lead** — PhD Mathematics, DS Manager
- **Claude Code Opus 4.6** — cloud, primary dev
- **Codex 5.3+** — local VS Code, secondary dev

## Key Learnings

- LLMs add genuine value for news interpretation and signal conflict resolution, but sub-strategies should stay rule-based. LLMs synthesise on top, they don't replace the scoring.
- At $3–7/month LLM cost, paid APIs are cheaper and more reliable than running local models.
- Defense in depth matters: 4-layer pipeline (Strategy → Moderation → Risk → Execution) catches errors no single layer would.
- Volume is fetched but never used — deliberate simplicity. Potential future enhancement.
- Yield spread (^TNX - ^IRX) was removed because the proxy was inaccurate and never influenced any decision.

## Open Questions

- How will conviction calibration change position sizing once we have ~50 trades?
- When does the system move from Practice to Live? Requires US-7.1 (auth) + US-7.3 (slippage tracking).
- Is moderation worth 3x the LLM cost? US-2.3 will answer with data.

## Related Notes

- [[Multi-LLM Pipeline Architecture]]
- [[Sophistication Roadmap]]
- [[Risk and Governance Framework]]
- [[Data Pipeline Rationale]]
- [[Backtesting and Validation]]
- [[Order Management and Execution]]
