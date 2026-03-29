---
tags: [investment-agent, overview, status]
status: active
last_updated: 2026-03-29
---

# Project Overview

Autonomous investment agent that trades US equities via the Trading 212 Practice API using a multi-LLM pipeline. Built as a personal quant system — innovation, simplicity, elegance, transparency.

## Current Status

**POC v1.0** — deployed to VPS, collecting live performance data on Trading 212 Practice.

- 1011+ tests collected
- 36 user stories delivered, 15 in pipeline (71% progress)
- Configurable scheduling: 3 DST-aware intraday cycles (10:00/12:30/15:15 America/New_York) or 2 standard cycles (07:00/19:00 UTC), Mon–Fri
- NYSE market holidays auto-skipped
- Dashboard: 11-page authenticated surface live at `https://zeninvest.zenouz.ai`, plus safe public demo mode
- Conversational trading: shared Slack/dashboard sessions with confirmation gating
- Evolution planner: authenticated natural-language change planning with validation matrix

## Pipeline at a Glance

```
Orchestrator (3 cycles/day, configurable)
  ├── Market Data     → yfinance + Finnhub + Alpha Vantage + earnings calendar
  ├── Universe Screen → Sector-balanced, cap-tiered, correlation-aware (~6900 seed)
  ├── Market Guidance → Point-in-time guidance snapshots tilt screening + enrich context
  ├── Strategy        → Momentum + Mean Rev + Factor → Claude Sonnet synthesis
  ├── Moderation      → GPT-4o (skeptic) + Gemini Flash (risk) → consensus
  ├── Risk            → 11 hard rules, VETO power, never LLM-overridden
  ├── Opportunity     → UOV scoring + ranked BUY queue
  ├── Execution       → T212 API: market + stop-loss + trailing + limit + dedup
  ├── Order Mgmt      → Execution quality telemetry, partial fill recovery
  ├── Notifications   → Slack + Email alerts (fail-open)
  └── Journal         → Per-trade journals, daily + weekly reports
```

## Recent Deliveries (since 2026-03-18)

- **US-1.9** Conversational Trading Workflow — multi-turn Slack/dashboard sessions, confirm/reject gating, audited action ledgers
- **US-1.10** Evolution Planner Phase 1 — authenticated planner, clarification loop, validation matrix, risk classification
- **US-2.5** Market Guidance Layer — guidance snapshots, sector scores, screening tilt, per-cycle influence audit
- **US-2.6** Strategy Episode Attribution — git-backed episodes, cycle fingerprints, authenticated review
- **US-3.3** Correlation-Aware Screening — duplicate exposure flagging before BUY
- **US-4.2** Earnings Calendar — earnings-date awareness across strategy/moderation/risk
- **US-7.2** Partial Fill Resubmission — conservative BUY-only fill recovery
- **US-7.3** Execution Quality & Slippage — market-order telemetry, slippage rollups, threshold alerts
- **US-7.5** Quick Hardening Slice — HALTED auto-recovery, off-hours annotations, peak inflation detection, DB CHECK constraints
- **US-7.8** Safe Public Demo Dashboard — sanitized public read models, preview-only private tabs, ingress hardening

## Next Priorities

1. **US-8.1** Open-Source Launch Prep — MIT LICENSE, CONTRIBUTING, CI (pytest + mypy), community-ready repo
2. **US-1.11** Branch-Based Evolution Runner — isolated branch workspace, scoped edits, review-ready PRs
3. **US-2.1 / US-2.2** Conviction Calibration + Dynamic Strategy Weighting — data-gated, needs ~50 trades

## Tech Stack

- **Language:** Python 3.11, Poetry
- **LLMs:** Claude Sonnet 4.5 (strategy), GPT-4o (skeptic), Gemini 2.5 Flash (risk)
- **Data:** yfinance, Finnhub, Alpha Vantage, Brave Search, Tavily, SEC EDGAR
- **Execution:** Trading 212 Practice API (httpx)
- **Storage:** SQLite (WAL mode) + Alembic migrations
- **Scheduling:** APScheduler
- **Dashboard:** FastAPI + React (Vite), Docker Compose, canonical HTTPS via Cloudflare + nginx
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
- Conversational workflows need explicit confirmation gates — letting LLMs execute without human sign-off is a governance failure, not a UX feature.
- Point-in-time guidance snapshots are more useful than live macro lookups because they persist and audit cleanly.
- Strategy episode attribution needs to be git-backed to survive prompt/config/logic drift across deploys.

## Open Questions

- How will conviction calibration change position sizing once we have ~50 trades?
- When does the system move from Practice to Live? Execution quality telemetry (US-7.3) is now delivered. Calibration data remains the main gate.
- Is moderation worth 3x the LLM cost? US-2.3 will answer with data.

## Related Notes

- [[Multi-LLM Pipeline Architecture]]
- [[Sophistication Roadmap]]
- [[Risk and Governance Framework]]
- [[Data Pipeline Rationale]]
- [[Backtesting and Validation]]
- [[Order Management and Execution]]
