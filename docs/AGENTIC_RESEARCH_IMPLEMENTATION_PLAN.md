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
| 1 | Create `src/agents/research/` module; providers (base, brave, tavily, router) | A | 1 session |
| 2 | SEC EDGAR client (`sec_search.py`) — direct HTTP, no LangChain | A | 0.5 session |
| 3 | ResearchCache, ResearchBudget, ResearchExecutor; ResearchLog model + migration | A | 1 session |
| 4 | Add `research` config block to settings.yaml; Settings properties in config.py | A | 0.5 session |
| 5 | Tests: providers, cache, budget, executor (mock APIs) | A | 0.5 session |
| 6 | Wire tool-use into Strategy engine (`synthesize_with_claude`) | B | 1 session |
| 7 | Wire tool-use into Moderation (GPT-4o skeptic, Gemini risk) | C | 1 session |
| 8 | Dashboard research panel, API `/api/research/*`, Slack, EventsLog | D | 1 session |

**Total:** ~6–7 sessions. Phases A–D are sequential; B and C can be parallelised after A.

## Phase A Checklist

- [ ] `src/agents/research/providers/base.py` — `SearchProviderProtocol`, `SearchResult`
- [ ] `src/agents/research/providers/brave.py` — Brave Search client (reuse HTTP patterns from `brave_enrichment`)
- [ ] `src/agents/research/providers/tavily.py` — Tavily client
- [ ] `src/agents/research/providers/router.py` — ProviderRouter (primary/fallback/additional)
- [ ] `src/agents/research/sec_search.py` — SEC EDGAR (direct API)
- [ ] `src/agents/research/cache.py` — ResearchCache (4h TTL)
- [ ] `src/agents/research/budget.py` — ResearchBudget (per-member + £50 cap)
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
