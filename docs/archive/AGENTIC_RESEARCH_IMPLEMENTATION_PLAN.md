---
tags: [agentic-research, implementation, us-4.4]
status: delivered
last_updated: 2026-03-29
archived: true
---

# US-4.4 Agentic Research — Implementation Plan

> **Archived 2026-03-29:** All tasks delivered. Architecture and canonical reference: [AGENTIC_RESEARCH.md](AGENTIC_RESEARCH.md). Routing policy: [FOLLOWUP_RESEARCH_ROUTING_PLAN.md](FOLLOWUP_RESEARCH_ROUTING_PLAN.md).

## Canonical Identifiers Used In This Plan

- Members: `strategy`, `skeptic`, `risk`
- Tool names: `web_search`, `news_search`, `sector_search`, `sec_search`, `macro_search`
- Feature flags: `research.strategy_research_enabled`, `research.skeptic_research_enabled`, `research.risk_research_enabled`
- Caps: `20/8/7` with `max_total_research_calls_per_cycle=35`

## Context

- **Status:** US-4.4 is delivered. Phase 0 and Phases A-D are complete.
- **Follow-on stories:** US-2.1/2.2 (calibration) and US-5.2 (parameter sensitivity) remain separate, later-stage work and are not blockers for US-4.4 completion.

## Execution Order (Delivered)

| # | Task | Phase | Est. |
|---|------|-------|------|
| 1 | Create `notebooks/research_api_investigation.ipynb` (Phase 0) | 0 | done |
| 2 | Run Phase 0; document Brave vs Tavily recommendation | 0 | done |
| 3 | Create `src/agents/research/` module; providers (base, brave, tavily, router) | A | 1 session |
| 4 | SEC EDGAR client (`sec_search.py`) — direct HTTP, no LangChain | A | 0.5 session |
| 5 | ResearchCache, ResearchBudget, ResearchExecutor; ResearchLog model + migration | A | 1 session |
| 6 | Add `research` config block to settings.yaml; caps (20/8/7, total 35); `tavily_monthly_calls: 1000` | A | 0.5 session |
| 7 | Wire tool-use into Strategy engine (`synthesize_with_claude`) | B | 1 session |
| 8 | Wire tool-use into Moderation (GPT-4o skeptic, Gemini risk) | C | 1 session |
| 9 | Dashboard research panel, API `/api/research/*`, Slack, EventsLog | D | 1 session |

**Total:** ~6 sessions delivered. Phase 0 and Phases A-D are complete.

### Phase 0 Context

- **SEC EDGAR:** Free; no API key. Use `company_tickers.json` for ticker→CIK, then `data.sec.gov/submissions/CIK{cik}.json` for filing metadata. User-Agent header required.
- **Config caps:** `max_calls_per_member_per_cycle: {strategy: 20, skeptic: 8, risk: 7}`, `max_total_research_calls_per_cycle: 35`.

## Phase 0 Checklist (Complete)

- [x] `notebooks/research_api_investigation.ipynb` — sections 0.1–0.7 (Environment, Brave, Tavily, A/B, SEC EDGAR, Summary, Mock Tool Execution)
- [x] Brave vs Tavily recommendation documented (Brave primary, Tavily fallback)
- [x] SEC EDGAR parsing approach confirmed
- [x] Suggested caps validated (20/8/7, total 35)

## Phase A Checklist

- [x] `src/agents/research/providers/base.py` — `SearchProviderProtocol`, `SearchResult`
- [x] `src/agents/research/providers/brave.py` — Brave Search client (reuse HTTP patterns from `brave_enrichment`)
- [x] `src/agents/research/providers/tavily.py` — Tavily client
- [x] `src/agents/research/providers/router.py` — ProviderRouter (primary/fallback/additional)
- [x] `src/agents/research/sec_search.py` — SEC EDGAR (direct API)
- [x] `src/agents/research/cache.py` — ResearchCache (4h TTL)
- [x] `src/agents/research/budget.py` — ResearchBudget (per-member caps 20/8/7, total 35)
- [x] `src/agents/research/executor.py` — ResearchExecutor
- [x] `src/agents/research/tools.py` — tool definitions
- [x] `ResearchLog` model + Alembic migration
- [x] Config: `research` block in settings.yaml
- [x] Integration: `search_api_tracker.check_search_api_budget()` before each search
- [x] Tests passing; `research.enabled: false` default

## Phase B Checklist

- [x] Refactor `synthesize_with_claude()` for tool-use loop
- [x] Max 8 iterations, 30s timeout
- [x] `research.strategy_research_enabled: false` default

## Phase C Checklist

- [x] GPT-4o and Gemini tool-use loops
- [x] Feature flags per moderator (`skeptic_research_enabled`, `risk_research_enabled`)

## Phase D Checklist

- [x] Dashboard Research Activity panel
- [x] `GET /api/research/logs`, `/api/research/summary`
- [x] Slack research insights
- [x] EventsLog integration

## Doc Updates on Completion

| File | Update |
|------|--------|
| CLAUDE.md | Research rules, ResearchLog, config keys |
| ARCHITECTURE.md | Data flow: research tool layer |
| GOVERNANCE.md | ResearchLog audit, budget monitoring |
| DATA_RATIONALE.md | Research tools as data sources |
| DASHBOARD.md | Research panel |
| SOPHISTICATION_ROADMAP.md | US-4.4 status reflects delivered implementation |
