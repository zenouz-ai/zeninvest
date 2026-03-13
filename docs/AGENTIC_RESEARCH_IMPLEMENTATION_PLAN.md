---
tags: [agentic-research, implementation, us-4.4]
status: current
last_updated: 2026-03-13
---

# US-4.4 Agentic Research — Implementation Plan

> Step-by-step implementation guide. See [AGENTIC_RESEARCH.md](AGENTIC_RESEARCH.md) for full design.

## Context

- **Status:** US-1.7 (Dashboard) and US-1.4 (VPS deployment) are delivered. US-4.4 is the current focus.
- **Deferred:** US-2.1/2.2 (calibration), US-5.2 (parameter sensitivity), US-1.6 (Slack commands) — await data or later sprint.

## Todo List (Execution Order)

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

**Total:** ~6 sessions. Phase 0 complete. Phases A–D are sequential; B and C can be parallelised after A.

### Phase 0 Context

- **SEC EDGAR:** Free; no API key. Use `company_tickers.json` for ticker→CIK, then `data.sec.gov/submissions/CIK{cik}.json` for filing metadata. User-Agent header required.
- **Config caps:** `max_calls_per_member_per_cycle: {strategy: 20, skeptic: 8, risk: 7}`, `max_total_research_calls_per_cycle: 35`, `tavily_monthly_calls: 1000`.

## Phase 0 Checklist (Complete)

- [x] `notebooks/research_api_investigation.ipynb` — sections 0.1–0.7 (Environment, Brave, Tavily, A/B, SEC EDGAR, Summary, Mock Tool Execution)
- [x] Brave vs Tavily recommendation documented (Brave primary, Tavily fallback)
- [x] SEC EDGAR parsing approach confirmed
- [x] Suggested caps validated (20/8/7, total 35)

## Phase A Checklist

- [ ] `src/agents/research/providers/base.py` — `SearchProviderProtocol`, `SearchResult`
- [ ] `src/agents/research/providers/brave.py` — Brave Search client (reuse HTTP patterns from `brave_enrichment`)
- [ ] `src/agents/research/providers/tavily.py` — Tavily client
- [ ] `src/agents/research/providers/router.py` — ProviderRouter (primary/fallback/additional)
- [ ] `src/agents/research/sec_search.py` — SEC EDGAR (direct API)
- [ ] `src/agents/research/cache.py` — ResearchCache (4h TTL)
- [ ] `src/agents/research/budget.py` — ResearchBudget (per-member caps 20/8/7, total 35)
- [ ] `src/agents/research/executor.py` — ResearchExecutor
- [ ] `src/agents/research/tools.py` — tool definitions
- [ ] `ResearchLog` model + Alembic migration
- [ ] Config: `research` block in settings.yaml
- [ ] Integration: `search_api_tracker.check_search_api_budget()` before each search
- [ ] Tests passing; `research.enabled: false` default

## Phase B Checklist

- [ ] Refactor `synthesize_with_claude()` for tool-use loop
- [ ] Max 8 iterations, 30s timeout
- [ ] `research.strategy_research_enabled: false` default

## Phase C Checklist

- [ ] GPT-4o and Gemini tool-use loops
- [ ] Feature flags per moderator

## Phase D Checklist

- [ ] Dashboard Research Activity panel
- [ ] `GET /api/research/logs`, `/api/research/summary`
- [ ] Slack research insights
- [ ] EventsLog integration

## Doc Updates on Completion

| File | Update |
|------|--------|
| CLAUDE.md | Research rules, ResearchLog, config keys |
| ARCHITECTURE.md | Data flow: research tool layer |
| GOVERNANCE.md | ResearchLog audit, budget monitoring |
| DATA_RATIONALE.md | Research tools as data sources |
| DASHBOARD.md | Research panel |
| SOPHISTICATION_ROADMAP.md | US-4.4 → Delivered |
