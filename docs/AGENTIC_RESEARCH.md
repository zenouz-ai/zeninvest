---
tags: [agentic-research, tool-use, committee]
status: in-progress
last_updated: 2026-03-13
---

# Agentic Research

> Independent tool access for committee members — enabling each LLM to research tickers based on its role.

## Purpose

Transform the investment agent's committee pipeline from a **fixed data payload** model to an **agentic research** model where each LLM committee member can independently search for and retrieve information relevant to the stocks they're evaluating. This mirrors how a real investment committee works — each analyst brings their own research to the table, not just a shared briefing pack.

## Viability Assessment

### Current Status

This project is **US-4.4** in the sophistication roadmap. Status: **In Progress** — US-1.8 Dashboard VPS Deployment is complete. Implementation can proceed. See [Implementation Plan](#implementation-plan) below and [AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md](AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md) for the step-by-step checklist.

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

**Viable and recommended.** Implementation should proceed. Feature flags allow gradual rollout and A/B comparison.

### Phase 0 — API Investigation (Pre-Build)

Before any `src/` code, a Phase 0 notebook validates APIs and establishes baselines:

- **Location:** `notebooks/research_api_investigation.ipynb`
- **Sections:** 0.1 Environment, 0.2 Brave Search, 0.3 Tavily Search, 0.4 A/B Comparison, 0.5 SEC EDGAR, 0.6 Cost/Latency Summary, 0.7 Mock Tool Execution
- **Output:** Brave vs Tavily recommendation, suggested caps, SEC EDGAR parsing approach

**Phase 0 Recommendation (Brave vs Tavily):**

| Factor | Brave Search | Tavily |
|--------|--------------|--------|
| Latency | ~300–500 ms | ~800–1200 ms |
| Snippet quality | Good; raw snippets | LLM-optimised `content` field |
| Finance relevance | General web; no native filter | Native `topic: finance` filter |
| **Primary** | ✓ Use as primary | Fallback on timeout/5xx |
| **Fallback** | — | ✓ Use when Brave fails |

**Recommendation:** Brave as primary (lower latency, existing integration), Tavily as fallback. For `news_search`, Tavily's `topic: finance` is valuable — consider Tavily for news-heavy queries when Brave returns thin results.

### Existing Infrastructure (Reuse)

| Component | Location | Purpose | Agentic Research Use |
|-----------|----------|---------|----------------------|
| Brave Search / Tavily | `src/agents/market_data/brave_enrichment.py` | Enrichment, web search fallback | Research layer will use same APIs via new provider abstraction. Do *not* duplicate HTTP logic — extract or share. |
| Search API tracker | `src/utils/search_api_tracker.py` | Monthly call limits (2k each for brave_search, brave_answers, tavily) | Research calls consume from **same** monthly limits. Enforce before each research tool call. |
| API logging | `ApiLog` model | Audit trail for external calls | Research adds `ResearchLog` for per-call detail; `ApiLog` continues for search API calls (shared). |

**Budget model:** Research enforces **call caps** (primary) and **cost cap** (secondary):

- **Search API monthly limits** — shared with enrichment/fallback: Brave Search 2,000, Brave Answers 2,000, Tavily 1,000 calls/month.
- **Per-member caps per cycle:** Strategy 20, Skeptic 8, Risk 7. **Total per cycle:** 35 (hard limit).
- **Strategy typical usage:** 10–15 calls/cycle; focus on 5–10 high-conviction tickers, 2–3 searches each.
- **Cost cap:** £50/month — tracked in `CostLog`/`ResearchLog`. If any limit is hit, research is disabled (graceful degradation).

## The Problem

**Current architecture (pre-batch model):**

```
DataFetcher → gathers ALL data upfront
    ├── yfinance OHLCV + indicators
    ├── Finnhub analyst recs + insider sentiment
    ├── Alpha Vantage news sentiment
    ├── Macro intelligence (sector + economic news)
    └── Company profiles

Strategy (Claude) ← receives the same fixed payload
Moderation (GPT-4o + Gemini) ← receives the same fixed payload + strategy output
```

**Problems with this approach:**

1. **Stale context** — News fetched at cycle start may be hours old by the time strategy runs. Market-moving events mid-cycle are missed entirely.
2. **Uniform perspective** — All committee members see identical data. No diversity of research angles. This limits the value of having multiple models.
3. **Wasteful API calls** — Finnhub/AV are called for every screened ticker, even if the committee only deeply evaluates 5-10. The intraday deferred fetch helps but still front-loads.
4. **No follow-up ability** — If Claude's strategy identifies a concern ("AAPL may face regulatory headwinds"), it can't go verify that hypothesis. It either knows from the pre-fetched batch or it doesn't.
5. **Shallow news coverage** — Current Finnhub/AV news is limited to their APIs. No access to broader financial journalism, SEC filings commentary, or social sentiment.

## The Solution

Give each committee member tool access during their evaluation phase so they can independently research tickers based on their role.

```
DataFetcher → gathers CORE data (OHLCV, indicators, fundamentals)
    │
    ▼
Strategy (Claude Sonnet) ← core data + TOOL ACCESS
    │   Tools: web search, news search, SEC filing search
    │   Role: "Research analyst — investigate opportunities"
    │   Can: search for recent news, earnings commentary, competitive dynamics
    │
    ▼
Moderation — Skeptic (GPT-4o) ← core data + strategy output + TOOL ACCESS
    │   Tools: web search, news search, contrarian research
    │   Role: "Devil's advocate — find reasons the thesis is wrong"
    │   Can: search for bear cases, analyst downgrades, sector risks
    │
    ▼
Moderation — Risk Assessor (Gemini) ← core data + strategy + skeptic + TOOL ACCESS
    │   Tools: web search, macro/sector search
    │   Role: "Risk assessor — evaluate macro and tail risks"
    │   Can: search for macro events, correlations, sector rotation data
    │
    ▼
Risk Manager ← deterministic rules, NO tool access (unchanged)
```

### Key Principles

| Member | Mandate | Tools | Research Angle | Max Calls/Cycle |
|--------|---------|-------|-----------------|-----------------|
| **Claude (Strategy)** | Identify opportunities; verify thesis validity | web_search, news_search, sector_search, sec_search | Bulls case; recent news; company fundamentals; competitive positioning | 20 (typical 10–15) |
| **GPT-4o (Skeptic)** | Falsify thesis; find downsides | web_search, news_search, sector_search | Bears case; analyst downgrades; regulatory risks; sector headwinds; short theses | 8 |
| **Gemini (Risk)** | Evaluate tail risks and macro context | web_search, macro_search (defer until needed) | Macro events; volatility spikes; central bank actions; geopolitical; sector correlation | 7 |

## Architecture

### Research Tool Layer

Research tools are accessed via a standardised LLM tool-use interface. The `ResearchExecutor` is a low-latency wrapper that maps tool calls to real APIs.

#### Tool Definitions

| Tool | Description | Provider | Response Type | Cost | Rate Limit |
|------|-------------|----------|----------------|------|------------|
| `web_search(query: str, num_results: int = 5) → list[SearchResult]` | General-purpose web search for news, analysis, SEC filings | Brave Search API + Tavily (fallback, optionally additional) | Top N results with URL, title, snippet/content, domain | £0.003–0.006/call | 100/min |
| `news_search(ticker: str, query: str, num_results: int = 5) → list[NewsResult]` | Financial news search (earnings, upgrades, insider, filings) | Brave + Tavily (topic: finance; fallback/additional) | News + sentiment + source credibility | £0.005/call | 100/min |
| `sec_search(ticker: str, doc_type: str, num_results: int = 3) → list[SECResult]` | Search SEC filings for a company (10-K, 10-Q, 8-K, proxy) | SEC EDGAR API (direct HTTP; no LangChain) | Filing summary, key excerpts, filing date | Free | 10/min |
| `sector_search(sector: str, query: str, num_results: int = 5) → list[SectorResult]` | Search sector rotation, peer analysis, industry trends | Brave + Tavily (topic: finance; fallback) | Results ranked by recency and authority | £0.003/call | 100/min |
| `macro_search(query: str, num_results: int = 5) → list[MacroResult]` | Search macro events (Fed, inflation, geopolitics, correlations) | Brave + Tavily (topic: news; fallback) | Current headlines + economic calendar | £0.003/call | 100/min |

#### Search Provider Strategy

Search tools use a **provider abstraction** so the executor can call Brave and/or Tavily with configurable primary/fallback/additional behaviour:

- **Provider interface**: All search providers implement `SearchProviderProtocol` with `search(query, num_results, topic, time_range) → list[SearchResult]`. Results normalised to common `SearchResult(url, title, snippet/content)`.
- **Primary + fallback**: Call primary provider first; on timeout, rate-limit, or 5xx → retry with fallback provider.
- **Additional mode**: For `news_search` (optionally `macro_search`), when `additional_for_news: true`, call both providers and merge/dedupe results by URL for richer coverage (higher cost).
- **ProviderRouter**: Orchestrates primary → fallback chain and optional additional merge. Logs `provider` (brave | tavily) to `ResearchLog` for audit.

Config (see Configuration section): `search_providers.primary`, `search_providers.fallback`, `search_providers.additional_for_news`.

#### Tool Assignment Per Member

**Strategy (Claude):**
- `web_search` — general thesis verification
- `news_search` — recent earnings, guidance, insider activity
- `sec_search` — annual reports, quarterly filings, executive compensation trends
- `sector_search` — peer performance, industry tailwinds

**Skeptic (GPT-4o):**
- `web_search` — bear case, short theses, criticisms
- `news_search` — downgrades, regulatory issues, insider selling
- `sector_search` — sector headwinds, competitive pressure

**Risk Assessor (Gemini):**
- `web_search` — geopolitical, central bank decisions, systemic risks
- `macro_search` — Fed policy, inflation, unemployment, yield curve
- `sector_search` — sector rotation signals, correlation spikes

#### Research Cache

To avoid redundant API calls across committee members:

```python
class ResearchCache:
    """
    Deduplicates research across committee members.
    Key: (ticker, tool_name, normalized_query)
    TTL: 4 hours (research is timely; longer than market data cache)
    """
    def get(self, ticker: str, tool: str, query: str) -> Optional[list]:
        ...
    
    def set(self, ticker: str, tool: str, query: str, results: list) -> None:
        ...
```

#### Research Budget

**Call caps (primary constraint):** The binding limit is **search API monthly call count** (2,000 Brave Search, 2,000 Brave Answers, 1,000 Tavily) — shared with enrichment/fallback.

1. **Per-member caps per cycle:** Strategy 20, Skeptic 8, Risk 7 calls
2. **Total per cycle cap:** 35 (hard limit across all members)
3. **Cost cap:** £50/month — tracked via `CostLog`; secondary to call caps
4. **Graceful degradation** — if any cap hit, research is disabled (all members fall back to zero-tool-use)

Implementation:

```python
class ResearchBudget:
    """Tracks per-member, per-cycle, and monthly research spend."""
    
    def can_afford(self, member: str, tool_cost: float) -> bool:
        cycle_spent = self.get_cycle_spend(member)
        monthly_spent = self.get_monthly_spend()
        
        return (
            cycle_spent + tool_cost <= self.per_cycle_budget[member]
            and monthly_spent + tool_cost <= self.monthly_cap
        )
    
    def record_call(self, member: str, tool: str, cost: float) -> None:
        # Log to CostLog
        ...
```

#### Research Audit Trail

New database model:

```python
class ResearchLog(Base):
    __tablename__ = "research_logs"
    
    id = Column(Integer, primary_key=True)
    cycle_id = Column(String, ForeignKey("runs.cycle_id"))
    member = Column(String)  # "strategy", "skeptic", "risk"
    ticker = Column(String)
    tool_name = Column(String)
    query = Column(String)
    num_results = Column(Integer)
    results_json = Column(JSON)  # Full API response
    provider = Column(String)    # brave | tavily (which search API served the request)
    cost_usd = Column(Float)
    latency_ms = Column(Integer)
    cache_hit = Column(Boolean)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_research_logs_cycle_id", "cycle_id"),
        Index("ix_research_logs_member_ticker", "member", "ticker"),
    )
```

### Research-Aware LLM Calls

#### Strategy Engine

Transform `synthesize_with_claude()` to include tool-use (see Phase B for implementation details). Claude receives research tools and uses them to verify opportunity thesis with real-time data, earnings commentary, insider activity, and competitive dynamics.

#### Moderation Panel

Wire tool-use into GPT-4o (skeptic) and Gemini (risk assessor) (see Phase C for implementation details). Each moderator has distinct research mandate and tools aligned with their role.

### Efficiency Mechanisms

| Mechanism               | Purpose                                                        |
| ----------------------- | -------------------------------------------------------------- |
| **ResearchCache**       | Dedupe across members; key `(ticker, tool, normalized_query)`; 4h TTL |
| **Call order**          | Strategy → Skeptic → Risk — cache warms; Skeptic/Risk benefit from Strategy's prior searches |
| **Hard cap per member** | 20/8/7 — prevent runaway; enforce in `ResearchBudget`          |
| **Hard cap total**      | 35 per cycle — respect monthly search limits                    |
| **Prompt guidance**     | "Use tools sparingly; prefer 1–2 high-value searches per ticker" |
| **Provider selection**  | Phase 0 validated Brave primary, Tavily fallback               |

### Research Cache Deduplication

Research results are cached by `(ticker, tool_name, normalized_query)` with a 4-hour TTL. This prevents redundant API calls when multiple committee members evaluate the same ticker.

#### Research Budget Enforcement

Per-member and aggregate call caps prevent runaway usage. If any cap is hit, research is disabled (graceful degradation).

#### Research Audit Trail

All research calls logged to `ResearchLog` for observability, cost tracking, and post-hoc analysis.

### Browser Automation (Phase E)

Future phase: Enable researching dynamic content (real-time stock tickers, interactive company dashboards, paywalled financial sites). Hybrid strategy:

**Phase E design (planned, not Phase A-D):**

1. **Lite research (Phases A-D)** — Brave Search API + Tavily + SEC EDGAR (covers ~80% of use cases)
2. **Heavy research (Phase E)** — Browser automation for:
   - Real-time stock charts (daily highs/lows)
   - Investor relations pages (latest presentations)
   - Seeking Alpha premium articles (via browser)
   - SEC EDGAR full-text (filing details)
   - Company cash flow statements and balance sheets

**Implementation approach for Phase E:**

Uses Playwright or Selenium for site automation, headless Chrome in VPS, per-site recipes (SOP for each site), timeout enforcement, resource cleanup.

**Per-site recipes:**

| Site | Goal | Steps | Timeout | Auth Required |
|------|------|-------|---------|---------------|
| SEC EDGAR | Get full filing text | Search ticker → select doc_type → download HTML | 15s | No |
| Investor Relations | Get latest presentation | Parse IR page structure → find "Presentations" link | 20s | No |
| Seeking Alpha | Get premium earnings analysis | Login → search ticker → filter "Earnings" | 30s | Yes (email/pwd) |
| Yahoo Finance | Get real-time chart image | Navigate to quote page → screenshot chart widget | 10s | No |
| TradingView | Get technical chart | Navigate to ticker → apply indicators → screenshot | 15s | No |

**VPS resource management:**
- Browser pool size: 3 concurrent browsers (avoid VM overload)
- Page timeout: 20 seconds (fallback to cache if hangs)
- Session lifetime: 10 minutes per browser (kill/restart to prevent memory leaks)
- Disk space for screenshots: max 100 MB (LRU cleanup if exceeds)

## Data Sources

### Primary: Brave Search

Brave Search API provides:
- Real-time web indexing (fresher than Finnhub/AV)
- Financial news filter
- Sector/industry filter
- No tracking; privacy-respecting

Cost: ~£0.001 per search in bulk.

### Secondary: Tavily Search (fallback + optional additional)

Tavily Search API provides:
- LLM-optimised snippets (`content` field with NLP summaries or chunks)
- Native `topic` filter: `general`, `news`, `finance` — `finance` aligns with `news_search` and `sector_search`
- `time_range` filter (day, week, month) for recency
- `search_depth`: basic/fast (1 credit) or advanced (2 credits)

Used as **fallback** when Brave times out or is rate-limited, and optionally as **additional** source for `news_search` (call both, merge results, dedupe by URL).

| Factor | Brave Search | Tavily |
|--------|-------------|--------|
| Cost | Free tier: 2K/month; ~£0.003/call paid | 1K free/month; ~£0.006/call (basic) |
| Quality | Good for news + web | Optimised for LLM consumption |
| Latency | ~500ms | ~1s |
| Finance focus | General filters | Native `topic: finance` |

### SEC EDGAR — What It Is

**SEC EDGAR** (Electronic Data Gathering, Analysis, and Retrieval) is the U.S. Securities and Exchange Commission's system for corporate filings. All public U.S. companies must file here.

| Filing   | Purpose                                                           |
| -------- | ----------------------------------------------------------------- |
| **10-K** | Annual report — audited financials, MD&A, risk factors            |
| **10-Q** | Quarterly report — unaudited financials                           |
| **8-K**  | Current report — material events (M&A, exec changes, bankruptcy) |
| **Proxy**| Shareholder meeting materials — voting, exec compensation         |

**Benefits:** Free; no API key required. Institutional-grade primary source. The `sec_search` tool queries EDGAR for a ticker and returns structured excerpts (e.g. Risk Factors, MD&A) instead of relying on secondary news.

### Tertiary: Existing APIs

- **yfinance** — OHLCV, technical indicators (free, within rate limits)
- **Finnhub** — Analyst recommendations, insider sentiment (existing, budget constrained)
- **Alpha Vantage** — News sentiment, sector performance (existing, budget constrained)

### Future: Premium Sources

- **S&P Capital IQ** — Company fundamentals, credit ratings, equity research
- **FactSet** — Institutional research, consensus estimates
- **Seeking Alpha Premium** — Earnings transcripts, premium articles
- **StockTwits** — Retail sentiment

## Prompt Engineering

Research prompts for each committee member guide tool selection and synthesis.

### Strategy Prompt (Claude)

```
You are an investment research analyst tasked with identifying opportunities.

Your mandate:
- Research HIGH-CONVICTION candidate tickers for buy opportunities
- Verify thesis validity with evidence from recent news, earnings, and fundamentals
- Use your research tools to build a compelling bull case

You have access to research tools:
  • web_search(query, num_results) — general news and analysis
  • news_search(ticker, query, num_results) — financial news (earnings, upgrades, insider activity)
  • sec_search(ticker, doc_type, num_results) — SEC filings (10-K, 10-Q, 8-K)
  • sector_search(sector, query, num_results) — peer performance, sector trends

Research strategy for each candidate:
1. Verify recent narrative: Search for latest news on the ticker
2. Check earnings momentum: Search for recent earnings reports
3. Analyze insider activity: Search for insider buying/selling
4. Sector validation: Search sector peer performance
5. Competitive positioning: Search for competitive threats or market share wins

Synthesis:
- Cite sources for each research insight (news outlet, filing date, insider name)
- Rank conviction on 1-10 scale based on:
  - Recency of supporting evidence (fresh news > old data)
  - Consensus across sources (multiple sources > single mention)
  - Insider alignment (insiders buying > analyst upgrades > news sentiment)
- Output structured decision with ticker, conviction, research summary, reasoning

Remember: Recent evidence (last 7 days) is stronger than historical data.
```

### Skeptic Prompt (GPT-4o)

```
You are the skeptic on an investment committee. Your job is to FALSIFY the proposed thesis.

Your mandate:
- Find reasons the proposed buy is WRONG
- Challenge assumptions with contrarian research
- Identify hidden risks or recent deterioration

You have access to research tools:
  • web_search(query, num_results) — find criticisms, bear cases, risks
  • news_search(ticker, query, num_results) — find downgrades, regulatory issues, insider selling
  • sector_search(sector, query, num_results) — find sector headwinds, competitive threats

Skeptic research agenda:
1. Find downgrades: Search for recent analyst downgrades
2. Check insider selling: Search for insider selling or option exercises
3. Regulatory risks: Search for litigation, regulatory investigations
4. Sector headwinds: Search for sector-wide challenges
5. Valuation concerns: Search for valuation criticism
6. Competitive threats: Search for new competitors or disruptive threats

Synthesis:
- Cite sources and dates for each concern
- Produce skeptic score (1-5):
  - 1 = No material concerns; approve
  - 3 = Mixed signals; reduce size
  - 5 = Critical concerns; block
- Output reasoning and recommendation

Remember: Your job is to prevent overconfidence. Be thorough in finding weaknesses.
```

### Risk Assessor Prompt (Gemini)

```
You are the risk assessor. Your role is to identify macro and tail risks.

Your mandate:
- Evaluate systemic and macro risks that could derail the trade
- Assess sector correlation and rotation signals
- Identify geopolitical or policy risks

You have access to research tools:
  • web_search(query, num_results) — geopolitical, systemic risks, Fed decisions
  • macro_search(query, num_results) — inflation, unemployment, yield curve, central bank
  • sector_search(sector, query, num_results) — sector rotation, correlation spikes

Risk assessment agenda:
1. Central bank policy: Search for imminent Fed decisions
2. Geopolitical events: Search for geopolitical risks (tariffs, trade wars, sanctions)
3. Macro indicators: Search for inflation/unemployment/yield curve moves
4. Sector rotation: Search for sector rotation signals
5. Correlation spikes: Search for recent increases in sector correlation

Synthesis:
- Produce tail risk score (1-5):
  - 1 = Low macro risk; safe
  - 3 = Moderate macro risk; monitor
  - 5 = High tail risk; defer
- Output macro context and recommendation

Remember: Focus on tail risks and second-order effects, not first-order thesis criticism.
```

---

## Implementation Plan

### Overview

| Phase | Focus | Deliverables | Depends On |
|-------|-------|--------------|------------|
| **A** | Research tool layer | Providers, cache, budget, executor, ResearchLog | None |
| **B** | Strategy engine tool-use | Claude tool-use loop, research in synthesis | Phase A |
| **C** | Moderation tool-use | GPT-4o + Gemini tool-use | Phase A |
| **D** | Observability | Dashboard panel, Slack, API, events | Phase A, B, C |

### Execution Order

```mermaid
flowchart TD
    A[Phase A: Research Tool Layer] --> B[Phase B: Strategy Engine]
    A --> C[Phase C: Moderation Panel]
    B --> D[Phase D: Observability]
    C --> D
```

### Key Technical Decisions

1. **Provider layer:** Build `src/agents/research/providers/` with `BraveSearchClient`, `TavilySearchClient`, `ProviderRouter`. Reuse HTTP patterns from `brave_enrichment.py` but keep research modules independent (avoid circular imports). Call `search_api_tracker.check_search_api_budget()` before each search.
2. **SEC EDGAR:** Use direct SEC HTTP APIs (`data.sec.gov`, `www.sec.gov/cgi-bin/browse-edgar`). No LangChain. Optional `SEC_EDGAR_EMAIL` for User-Agent politeness.
3. **Budget enforcement:** `ResearchBudget` checks (a) per-member per-cycle (£0.30/0.20/0.20), (b) monthly £50 cap, (c) `check_search_api_budget(service)` before each Brave/Tavily call.
4. **Tool-use formats:** Claude uses `tool_use` blocks; OpenAI uses `function_calls`; Gemini uses `function_declarations`. Executor normalises tool names and parameters; each LLM client handles its own format.
5. **Config:** Add `research` block to `settings.yaml`; add `research_*` properties to `Settings` in `config.py`.

### File Structure

```
src/agents/research/
├── __init__.py
├── providers/
│   ├── __init__.py
│   ├── base.py      # SearchProviderProtocol, SearchResult
│   ├── brave.py     # BraveSearchClient
│   ├── tavily.py    # TavilySearchClient
│   └── router.py    # ProviderRouter
├── tools.py         # Tool definitions (name, description, input_schema)
├── cache.py         # ResearchCache
├── budget.py        # ResearchBudget
├── executor.py      # ResearchExecutor (orchestrates tools, cache, budget, logging)
├── sec_search.py    # SEC EDGAR client
└── prompts.py       # Research-specific prompt fragments (optional)
```

### Acceptance Criteria (All Phases)

- [ ] Phase A: Providers, cache, budget, executor, ResearchLog; tests pass; `research.enabled: false` default
- [ ] Phase B: Claude tool-use loop; max 8 iterations; ResearchLog entries; `research.strategy_research_enabled: false` default
- [ ] Phase C: GPT-4o and Gemini tool-use; skeptic/risk research; feature flags
- [ ] Phase D: Dashboard research panel, GET /api/research/*, Slack insights, EventsLog
- [ ] All research disabled when `research.enabled: false` or search/monthly cap hit
- [ ] Documentation updated: CLAUDE.md, ARCHITECTURE.md, GOVERNANCE.md, DATA_RATIONALE.md, DASHBOARD.md

---

## Implementation Phases

### Phase A — Research Tool Layer (1 session)

**Deliverables:**
- `src/agents/research/providers/base.py` — `SearchProviderProtocol`, `SearchResult` dataclass
- `src/agents/research/providers/brave.py` — Brave Search client (implements protocol)
- `src/agents/research/providers/tavily.py` — Tavily Search client (implements protocol)
- `src/agents/research/providers/router.py` — ProviderRouter (primary/fallback/additional logic)
- `src/agents/research/tools.py` — tool definitions
- `src/agents/research/web_search.py` — uses ProviderRouter (not direct Brave call)
- `src/agents/research/sec_search.py` — SEC EDGAR integration
- `src/agents/research/cache.py` — research cache (4h TTL)
- `src/agents/research/budget.py` — per-member budget enforcement
- `src/agents/research/executor.py` — tool execution + logging
- `ResearchLog` model + Alembic migration (includes `provider` column)
- Tests: budget enforcement, cache hits, tool execution, provider fallback

**Feature flag:** `research.enabled: false` (default)

**Integration:** Call `search_api_tracker.check_search_api_budget(SERVICE_BRAVE_SEARCH)` (or `SERVICE_TAVILY`) before each Brave/Tavily request. Log via `log_search_api_call()`. Research shares the 2,000 calls/month limit with enrichment.

**Claude Code Prompt:**

```
You are implementing the research tool layer for agentic research. Your job is to build the infrastructure that committee members will use to search for information.

Create:
1. Provider abstraction (providers/base.py, brave.py, tavily.py, router.py):
   - SearchProviderProtocol: search(query, num_results, topic, time_range) → list[SearchResult]
   - BraveSearchClient: wrapper around Brave Search API
   - TavilySearchClient: wrapper around Tavily Search API (topic: general|news|finance, search_depth)
   - ProviderRouter: primary → fallback on failure; optional additional merge for news_search
   - Normalise both providers to SearchResult(url, title, snippet/content)

2. SEC EDGAR client (sec_search.py):
   - Fetch and parse SEC filings for a ticker (10-K, 10-Q, 8-K)
   - Use direct SEC EDGAR API (https://www.sec.gov/cgi-bin/browse-edgar, data.sec.gov); no LangChain dependency
   - Extract key sections (MD&A, Risk Factors, Financial Statements) via HTML parsing or SEC JSON API
   - Returns: filing summary with key excerpts

3. Cache layer (cache.py):
   - Key: (ticker, tool_name, normalized_query)
   - TTL: 4 hours
   - Deduplicate across committee members
   - Implement: get(), set(), clear_expired()

4. Budget layer (budget.py):
   - Per-member per-cycle budget (strategy £0.30, skeptic £0.20, risk £0.20)
   - Monthly cap: £50
   - Methods: can_afford(), record_call()
   - Graceful degradation: if cap hit, all research disabled

5. Executor (executor.py):
   - Orchestrates tool execution, caching, budgeting, logging
   - Async tool call with timeout (20 seconds)
   - Audit trail to ResearchLog
   - Error handling and fallback

6. ResearchLog model:
   - columns: cycle_id, member, ticker, tool_name, query, results_json, provider (brave|tavily), cost_usd, latency_ms, cache_hit, error
   - indexes: (cycle_id), (member, ticker)

Test with in-memory SQLite fixtures. No real API keys needed for basic tests (mock Brave and Tavily responses).
```

### Phase B — Wire Into Strategy Engine (1 session)

**Deliverables:**
- `src/agents/strategy/engine.py` — refactor `synthesize_with_claude()` to use tool-use loop
- Tool-use loop: call Claude with tools, handle `tool_use` stop reason, execute, append results, iterate
- Error handling: max 8 iterations, timeout enforcement
- Feature flag: `research.strategy_research_enabled: false`
- Tests: tool-use loop, max iterations, decision parsing

**Claude Code Prompt:**

```
You are wiring research tool access into the strategy engine. The strategy now has a tool-use loop 
where Claude can call research tools during evaluation.

Refactor synthesize_with_claude() to:
1. Define research tools for Claude:
   - web_search, news_search, sec_search, sector_search
   - Each tool has name, description, input_schema

2. System prompt that instructs Claude to:
   - Research high-conviction candidates
   - Verify thesis validity with recent news
   - Cite sources for each research insight
   - Output structured decision with conviction, research summary, reasoning

3. Implement tool-use loop:
   - Call Claude with tools
   - If stop_reason == "tool_use": collect tool_use blocks, execute them
   - If stop_reason == "end_turn": parse decision and return
   - Max iterations: 8 (prevent infinite loops)
   - Timeout: 30 seconds total (enforce on each iteration)

4. Tool execution:
   - Call executor.execute_research_tool(member="strategy", tool_name, input)
   - Executor handles budget, cache, logging
   - Return results to Claude as tool_result

5. Error handling:
   - Budget exhausted: return error message, Claude adapts
   - Tool timeout: return partial result or "timeout" message
   - API error: return error message with fallback advice

6. Testing:
   - Mock Claude responses with tool_use blocks
   - Test loop termination (end_turn, max iterations, timeout)
   - Test decision parsing with various Claude outputs
   - Verify ResearchLog entries are created
```

### Phase C — Wire Into Moderation Panel (1 session)

**Deliverables:**
- `src/agents/moderation/panel.py` — refactor skeptic (GPT-4o) and risk (Gemini) to use tool-use/function-calling
- Feature flags: `research.skeptic_research_enabled`, `research.risk_research_enabled` (both false)
- Tests: tool-use loops for each member, decision parsing

**Claude Code Prompt:**

```
You are wiring research tool access into the moderation panel. The skeptic (GPT-4o) and risk assessor (Gemini) 
now have their own research tools to evaluate theses.

Refactor moderation calls:
1. Skeptic (GPT-4o) with function calling:
   - Tools: web_search, news_search, sector_search
   - System prompt: falsify thesis; find bear cases, downgrades, insider selling, sector risks
   - Function-calling loop: call GPT-4o, handle tool_calls, execute, continue
   - Max iterations: 6, timeout: 25 seconds
   - Output: skeptic_score (1-5), concerns, recommendation

2. Risk Assessor (Gemini) with tool use:
   - Tools: web_search, macro_search, sector_search
   - System prompt: evaluate tail risks; macro policy, geopolitical, sector rotation
   - Tool-use loop: call Gemini, handle tool_use, execute, continue
   - Max iterations: 6, timeout: 25 seconds
   - Output: risk_score (1-5), macro_context, recommendation

3. Executor integration:
   - Both call executor.execute_research_tool(member=member_name, ...)
   - Executor deduplicates with cache
   - Log all research calls with member name

4. Testing:
   - Mock GPT-4o and Gemini responses with tool_call/tool_use blocks
   - Test loop termination
   - Test deduplication across members
   - Verify vote parsing and decision integration

Feature flags allow gradual rollout:
- Enable research for strategy only first
- Then enable skeptic
- Finally enable risk
- Or run A/B test (research vs non-research cohorts)
```

### Phase D — Observability & Dashboard Integration (1 session)

**Deliverables:**
- Dashboard "Research Activity" panel (Phase 1.5)
- Slack research insights (formatted notifications)
- `/api/research/` endpoints for dashboard
- Event logger integration (EventsLog)
- Tests: dashboard data format, API response structure

**Claude Code Prompt:**

```
You are building observability for agentic research. The dashboard and notifications need to show 
what research the committee members conducted and what they found.

Deliverables:
1. Dashboard "Research Activity" panel:
   - Table of research calls (member, ticker, tool, query, provider, results_json, cost, latency, cache_hit)
   - Filters: by member, by cycle, by ticker
   - Expandable rows: show full results and tool response
   - Summary stats: total calls, total cost, cache hit rate (%)

2. Slack research insights:
   - Format: "[Research] Claude researched AAPL (web_search): found 3 bullish articles, 1 downgrade"
   - Include citations (URLs, sources)
   - Cost breakdown if cycle_cost > £0.50

3. API endpoints:
   - GET /api/research/logs?cycle_id=... — list research calls
   - GET /api/research/logs/{id} — full research call details
   - GET /api/research/summary?from=...&to=... — aggregated stats

4. Event logger:
   - Emit "research_call" events for each tool execution
   - Metadata: member, ticker, tool, cost, cache_hit, results summary
   - Used by dashboard SSE stream

5. Testing:
   - Verify event format matches EventsLog schema
   - Test API response structure (pagination, filters)
   - Test Slack message formatting
```

---

## Configuration

Add to `config/settings.yaml`:

```yaml
research:
  enabled: false
  
  # Feature flags per committee member
  strategy_research_enabled: false
  skeptic_research_enabled: false
  risk_research_enabled: false
  
  # Per-member budget (GBP per cycle)
  per_member_budget_per_cycle:
    strategy: 0.30
    skeptic: 0.20
    risk: 0.20
  
  # Monthly aggregate cap (GBP)
  monthly_cap: 50.0
  
  # Tool-use loop config
  max_iterations_per_member: 8
  timeout_per_member_seconds: 30
  
  # Cache config
  cache_ttl_hours: 4
  max_cache_entries: 10000
  
  # Search provider strategy: primary, fallback, optional additional
  search_providers:
    primary: brave       # brave | tavily
    fallback: tavily     # tavily | brave | none
    additional_for_news: false  # If true: news_search calls both Brave + Tavily, merges results
  
  # Research tools config
  brave_search:
    enabled: true
    num_results_default: 5
    timeout_seconds: 10
  
  tavily_search:
    enabled: true
    search_depth: basic   # basic | fast | advanced (advanced = 2 credits)
    topic_mapping:
      web_search: general
      news_search: finance
      sector_search: finance
      macro_search: news
    timeout_seconds: 10
  
  sec_search:
    enabled: true
    num_results_default: 3
    timeout_seconds: 15
  
  # Research modes
  mode: shadow  # "shadow" (log but don't use) or "active" (use in decisions)
  
  # Dashboard
  dashboard_research_panel_enabled: false
```

---

## Environment Variables

Required (add to `.env`):

```
BRAVE_SEARCH_API_KEY=...          # Brave Search ($5/1k requests; 50 RPS; free $5 credits/month)
BRAVE_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
```

Optional (required if Tavily is primary, fallback, or additional):

```
TAVILY_API_KEY=...                # Tavily Search (free: 1K credits/month; pay-as-you-go: $0.008/credit; Project: $30/month for 4k credits)
SEC_EDGAR_EMAIL=your_email@domain.com  # For politeness headers; optional but recommended
RESEARCH_CACHE_REDIS_URL=redis://localhost:6379  # If using Redis instead of in-process cache
```

---

## Risk Assessment

Combined risks from both PROJECT and IMPLEMENTATION_PLAN:

| Risk | Likelihood | Impact | Mitigation | Owner |
|------|-----------|--------|-----------|-------|
| **Runaway API costs** | Medium | Medium | Per-member budgets, monthly cap £50, cost tracking, graceful degradation | Implementation |
| **Increased cycle latency** | High | Medium | Parallel tool calls, timeout enforcement (30s per member), cache hits, feature flags | Implementation |
| **LLM hallucinating research** | Low | High | All results are real API responses (not LLM-generated); audit trail in ResearchLog | Design |
| **Research leading to overconfidence** | Medium | Medium | Skeptic mandate explicitly contrarian; risk assessor evaluates tail risks | Prompt design |
| **Tool-use loops not terminating** | Low | High | Max 8 iterations per member, global timeout, force end-turn parsing | Implementation |
| **Cache poisoning** | Very Low | High | Cache key is (ticker, tool, query); normalized queries; TTL 4h | Cache design |
| **Budget exhaustion early in month** | Low | High | Monitor monthly spend via dashboard; adjust per-member budgets if needed | Operations |
| **Brave Search API downtime** | Low | Medium | Fallback to Tavily; cached results; emit alert if both providers down; cycle continues | Executor |
| **Tavily API downtime** | Low | Medium | Used as fallback only; if both Brave and Tavily fail, emit alert; cycle continues with cached/partial results | Executor |
| **SEC EDGAR parser errors** | Low | Medium | Graceful fallback to snippet; log parse errors; retry with different doc_type | Executor |
| **Skeptic doing insufficient falsification** | Medium | Medium | Test skeptic prompts with known theses; audit research queries in dashboard; A/B test | Prompt design |

---

## Success Metrics

After 4 weeks with research enabled on live account:

1. **Decision quality**: Hit rate of research-influenced decisions vs baseline (target: +5-10% improvement)
2. **Skeptic effectiveness**: Track research-influenced downgrades (# of times skeptic research led to veto, target: >5 per month)
3. **Diversity**: Query overlap between members < 30% (target: 10-15%)
4. **Cost efficiency**: Research cost per cycle < £0.50 (target: £0.30)
5. **Latency impact**: Cycle time increase < 2 minutes (target: +1 minute)
6. **Cache efficiency**: Cross-member cache hit rate > 20% (target: 30%)

---

## Roadmap Integration

When implementing this feature, update these documentation files:

| File | Update |
|------|--------|
| `SOPHISTICATION_ROADMAP.md` | Add/update US-4.4 row with status, blockers, delivered |
| `CLAUDE.md` | Add research architecture rules, config, ResearchLog model, quick commands (`--research-diagnostic`) |
| `ARCHITECTURE.md` | Data flow diagram: add research tool layer, tool-use loops per committee member |
| `GOVERNANCE.md` | Add ResearchLog audit trail, BRAVE_SEARCH_API_KEY env var, monthly budget monitoring |
| `DATA_RATIONALE.md` | Add section: research tools as data sources, deduplication strategy |
| `DASHBOARD.md` | Add Phase D research panel: table, filters, event stream |

---

## Related Notes

- [Agentic Research Implementation Plan](AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md) — Step-by-step checklist
- [Architecture](ARCHITECTURE.md) — Data flow with research tool layer
- [Governance](GOVERNANCE.md) — Audit trail (ResearchLog, cost tracking, monthly budgets)
- [Dashboard](DASHBOARD.md) — Research Activity panel (Phase D)
- [Data Rationale](DATA_RATIONALE.md) — Research tools as data sources
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-4.4 delivery tracking
