# Agentic Research Implementation Plan

**Created:** 2026-03-10
**Status:** Planned — to implement after US-1.8 Dashboard VPS Deployment (code implemented; VPS deploy via Docker when ready)
**Reference:** [AGENTIC_RESEARCH_PROJECT.md](AGENTIC_RESEARCH_PROJECT.md)

---

## 1. Current State Summary

### LLM Usage Today

| Component | Model | Call Pattern | Data Source |
|-----------|-------|--------------|-------------|
| Strategy | Claude Sonnet | Single-shot `messages.create` | Fixed payload from DataFetcher (sub-strategies, analyst data, news sentiment, company profiles) |
| Moderation (Skeptic) | GPT-4o | Single-shot `chat.completions.create` | Same market context + strategy output |
| Moderation (Risk) | Gemini Flash | Single-shot `generate_content` | Same market context + strategy output |
| Risk Manager | — | Deterministic Python | No LLM (unchanged) |

**Data flow:** DataFetcher gathers OHLCV, indicators, fundamentals, Finnhub analyst recs, Alpha Vantage news, macro intelligence upfront. All committee members receive the same fixed payload. No tool use or function calling exists today.

### Relevant Context

- **Dashboard:** Phase 1 + Phase 1.5 Analytics Lite done; US-1.8 implemented (Docker service, port 8000; SPA served by FastAPI)
- **Roadmap:** 7 delivered, 1 in progress (US-1.7), 16 in pipeline
- **ID:** This project is **US-4.4** (US-4.1 is reserved for Volume Signals)

---

## 2. Viability Assessment

### Benefits

| Benefit | Rationale |
|---------|-----------|
| **Stale context mitigation** | News fetched at cycle start may be hours old; research tools allow on-demand verification mid-evaluation |
| **Differentiated perspectives** | Each member has a distinct research mandate (opportunity vs thesis falsification vs macro risk) |
| **Reduced wasteful API calls** | Finnhub/AV currently called for all screened tickers; research defers to on-demand per-ticker |
| **Follow-up ability** | Claude can search to verify hypotheses before deciding |
| **Broader coverage** | Access to SEC filings, general web search beyond Finnhub/AV |
| **Foundation for future** | Tool-use infrastructure benefits earnings calendar, sector rotation, etc. |

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Runaway API costs | Medium | Medium | Per-member budgets, monthly cap, cache dedup |
| Increased cycle latency | High | Medium | Parallel tool calls, timeout enforcement, cache |
| LLM hallucinating research | Low | High | All research results are real API responses |
| Research leading to overconfidence | Medium | Medium | Skeptic mandate is explicitly contrarian |
| Tool-use loops not terminating | Low | High | Max iterations per member, timeout on evaluation |

### Verdict

**Viable and recommended.** Implementation should proceed after US-1.8 and before ML features (US-6.x). Feature flags allow gradual rollout and A/B comparison.

---

## 3. Implementation Phases (A–D)

### Phase A — Research Tool Layer (1 session)

Create `src/agents/research/` with: `tools.py`, `web_search.py`, `news_search.py`, `sec_search.py`, `cache.py`, `budget.py`, `executor.py`. Add `ResearchLog` model and Alembic migration.

### Phase B — Wire Into Strategy Engine (1 session)

Convert `synthesize_with_claude` to tool-use loop. Feature flag: `research.strategy_research_enabled` (default: false).

### Phase C — Wire Into Moderation Panel (1 session)

Add function-calling/tool-use loops for GPT-4o (skeptic) and Gemini (risk assessor). Feature flags per member.

### Phase D — Observability & Dashboard Integration (1 session)

Dashboard "Research Activity" panel, Slack research insights, event logger, `/api/research/` endpoints.

---

## 4. Success Metrics

After 4 weeks with research enabled:

1. Decision quality: higher hit rate vs baseline
2. Skeptic effectiveness: track "research-influenced downgrades"
3. Diversity: query overlap between members < 30%
4. Cost efficiency: research cost per cycle < £0.50
5. Latency impact: cycle time increase < 2 minutes
6. Cache efficiency: cross-member cache hit rate > 20%

---

## 5. Roadmap and Document Updates (when implementing)

- Add US-4.4 to SOPHISTICATION_ROADMAP.md
- Update CLAUDE.md (architecture rule, config, ResearchLog)
- Update ARCHITECTURE.md (data flow)
- Update GOVERNANCE.md (BRAVE_SEARCH_API_KEY, research_logs)
- Update DATA_RATIONALE.md (research tools section)
- Update DASHBOARD_VISUALISATION_PROJECT.md (Phase D reference)
