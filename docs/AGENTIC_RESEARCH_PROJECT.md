# Agentic Research — Independent Tool Access for Committee Members

## Project Summary

Transform the investment agent's committee pipeline from a **fixed data payload** model to an **agentic research** model where each LLM committee member can independently search for and retrieve information relevant to the stocks they're evaluating. This mirrors how a real investment committee works — each analyst brings their own research to the table, not just a shared briefing pack.

---

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

---

## The Solution: Agentic Research Per Committee Member

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

### Key Principle: Differentiated Research Mandates

Each model isn't just "searching the web" — they have distinct research mandates that produce genuinely different perspectives:

| Member | Research Mandate | What They Search For | What They Ignore |
|--------|-----------------|---------------------|-----------------|
| **Claude (Strategy)** | Opportunity discovery | Bullish catalysts, earnings beats, product launches, competitive moats, insider buying | Already knows the bear case from data |
| **GPT-4o (Skeptic)** | Thesis falsification | Analyst downgrades, regulatory risk, competitor threats, management red flags, short interest | Deliberately avoids confirming evidence |
| **Gemini (Risk)** | Systemic risk assessment | Macro events, sector correlations, geopolitical risk, credit spreads, volatility regime | Individual stock catalysts (that's Claude's job) |

---

## Architecture Design

### 1. Research Tool Layer (`src/agents/research/`)

A shared tool layer that wraps multiple data sources into a clean interface any LLM can use via function calling / tool use.

```
src/agents/research/
├── __init__.py
├── tools.py              # Tool definitions (schemas for each LLM provider)
├── web_search.py         # Web search provider (Brave Search API or SerpAPI)
├── news_search.py        # Financial news aggregator (Finnhub + RSS + web)
├── sec_search.py         # SEC EDGAR filing search (free API)
├── social_sentiment.py   # Reddit/StockTwits sentiment (future, optional)
├── cache.py              # Research cache (dedup across members within a cycle)
└── budget.py             # Per-cycle research budget enforcement
```

#### Tool Definitions

```python
# tools.py — provider-agnostic tool schemas

RESEARCH_TOOLS = {
    "search_recent_news": {
        "description": "Search for recent financial news about a specific company or ticker. Returns headlines, summaries, sources, and publication dates from the last 7 days.",
        "parameters": {
            "query": "Search query (e.g. 'AAPL earnings Q1 2026' or 'Apple regulatory EU')",
            "ticker": "Stock ticker for targeted results",
            "days_back": "How many days back to search (default: 7, max: 30)",
            "max_results": "Maximum results to return (default: 5)"
        }
    },
    "search_web": {
        "description": "General web search for financial analysis, commentary, or market context. Use for broader research beyond news headlines.",
        "parameters": {
            "query": "Search query",
            "max_results": "Maximum results (default: 5)"
        }
    },
    "search_sec_filings": {
        "description": "Search recent SEC filings (10-K, 10-Q, 8-K, insider transactions) for a company.",
        "parameters": {
            "ticker": "Stock ticker",
            "filing_types": "List of filing types to search (default: ['10-K', '10-Q', '8-K'])",
            "days_back": "How far back to search (default: 90)"
        }
    },
    "get_sector_analysis": {
        "description": "Get current sector-level analysis including performance, rotation trends, and macro headwinds/tailwinds.",
        "parameters": {
            "sector": "Sector name (e.g. 'Technology', 'Healthcare')",
            "include_etf_flows": "Include ETF flow data (default: true)"
        }
    },
    "browse_financial_site": {
        "description": "Navigate to a financial website and extract specific information using an AI-driven browser agent. Use for sites that require navigation (clicking, scrolling, searching) or have dynamic content that simple web search cannot access. Examples: earnings call transcripts, analyst commentary pages, company investor relations, broker dashboards.",
        "parameters": {
            "url": "Starting URL to navigate to",
            "task": "Natural language description of what to find and extract",
            "extract_schema": "Optional: structured fields to extract (e.g. {'analyst': 'string', 'rating': 'string', 'target_price': 'number'})",
            "max_steps": "Maximum browser navigation steps (default: 10, max: 20)"
        }
    }
}
```

#### Tool Assignment Per Member

Not every member gets every tool. This enforces the differentiated mandate:

```python
MEMBER_TOOL_ACCESS = {
    "strategy": ["search_recent_news", "search_web", "search_sec_filings", "browse_financial_site"],
    "skeptic": ["search_recent_news", "search_web", "browse_financial_site"],
    "risk_assessor": ["search_web", "get_sector_analysis"],
}
```

### 2. Research-Aware LLM Calls

Each committee member's LLM call changes from a single prompt → response to a multi-turn tool-use conversation.

#### Strategy Engine (Claude) — Already supports native tool use

```python
# src/agents/strategy/engine.py — modified flow

async def evaluate_ticker(self, ticker: str, core_data: dict) -> StrategyDecision:
    tools = get_tools_for_member("strategy")

    messages = [
        {
            "role": "user",
            "content": self._build_strategy_prompt(ticker, core_data)
        }
    ]

    # Multi-turn tool use loop
    while True:
        response = await anthropic.messages.create(
            model="claude-sonnet-4-5-20250929",
            messages=messages,
            tools=tools,
            max_tokens=4096,
            system=STRATEGY_SYSTEM_PROMPT  # includes research mandate
        )

        # Check if Claude wants to use a tool
        if response.stop_reason == "tool_use":
            tool_results = await execute_tool_calls(response.content, budget="strategy")
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Final response — parse decision
        return self._parse_strategy_response(response)
```

#### Moderation Panel (GPT-4o + Gemini) — Function calling

```python
# src/agents/moderation/panel.py — modified flow

async def run_skeptic(self, ticker: str, core_data: dict, strategy: StrategyDecision):
    tools = get_tools_for_member("skeptic")

    # GPT-4o function calling loop
    messages = [{"role": "user", "content": self._build_skeptic_prompt(ticker, core_data, strategy)}]

    while True:
        response = await openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,  # OpenAI function calling format
        )

        if response.choices[0].finish_reason == "tool_calls":
            tool_results = await execute_tool_calls(response, budget="skeptic")
            messages.extend(tool_results)
            continue

        return self._parse_skeptic_response(response)


async def run_risk_assessor(self, ticker: str, core_data: dict, strategy: StrategyDecision, skeptic: dict):
    tools = get_tools_for_member("risk_assessor")

    # Gemini tool use loop
    # Similar pattern, adapted for Google AI SDK
    ...
```

### 3. Research Cache (Cross-Member Dedup)

If Claude already searched "AAPL earnings Q1 2026" during strategy, GPT-4o shouldn't make the same API call during moderation. Cache at the cycle level.

```python
# src/agents/research/cache.py

class ResearchCache:
    """Per-cycle research cache. Prevents duplicate API calls across committee members."""

    def __init__(self, cycle_id: str):
        self.cycle_id = cycle_id
        self._cache: dict[str, Any] = {}

    def cache_key(self, tool_name: str, params: dict) -> str:
        """Deterministic key from tool + sorted params."""
        return f"{tool_name}:{json.dumps(params, sort_keys=True)}"

    async def get_or_fetch(self, tool_name: str, params: dict, fetch_fn) -> Any:
        key = self.cache_key(tool_name, params)
        if key in self._cache:
            logger.info(f"Research cache HIT: {tool_name} for {params.get('ticker', params.get('query', ''))}")
            return self._cache[key]

        result = await fetch_fn(params)
        self._cache[key] = result
        return result
```

### 4. Research Budget Enforcement

Each member gets a per-cycle research budget to prevent runaway API costs and latency.

```python
# src/agents/research/budget.py

RESEARCH_BUDGETS = {
    "strategy": {
        "max_tool_calls_per_ticker": 3,     # Claude can make up to 3 searches per stock
        "max_tool_calls_per_cycle": 15,      # Total across all stocks in a cycle
        "max_latency_seconds": 10,           # Timeout per tool call
    },
    "skeptic": {
        "max_tool_calls_per_ticker": 2,
        "max_tool_calls_per_cycle": 10,
        "max_latency_seconds": 10,
    },
    "risk_assessor": {
        "max_tool_calls_per_ticker": 1,      # Gemini focuses on macro, fewer per-ticker searches
        "max_tool_calls_per_cycle": 8,
        "max_latency_seconds": 10,
    },
}
```

### 5. Research Audit Trail

Every research action is logged for transparency and debugging.

```python
# New model in src/data/models.py

class ResearchLog(Base):
    __tablename__ = "research_logs"

    id = Column(Integer, primary_key=True)
    cycle_id = Column(String, index=True)
    member = Column(String)            # strategy | skeptic | risk_assessor
    ticker = Column(String, index=True)
    tool_name = Column(String)         # search_recent_news | search_web | etc
    query = Column(Text)               # What they searched for
    results_summary = Column(Text)     # Truncated result summary
    cache_hit = Column(Boolean)        # Was this served from cache?
    latency_ms = Column(Integer)       # How long the search took
    cost_usd = Column(Float)           # API cost if applicable
    timestamp = Column(DateTime, default=datetime.utcnow)
```

---

## Data Source Selection

### Primary: Brave Search API (recommended)

| Factor | Brave Search | SerpAPI | Tavily |
|--------|-------------|---------|--------|
| Cost | Free tier: 2,000 queries/month. $5/1000 after. | $50/month for 5,000 | $0.01/search |
| Quality | Good for news + web | Best Google results | Optimised for LLM use |
| Latency | ~500ms | ~1-2s | ~1s |
| Financial focus | General (good enough) | General | Can be tuned |

**Recommendation:** Start with **Brave Search API** (free tier covers ~65 queries/day, enough for 3 cycles × ~7 stocks × 3 members). Upgrade to Tavily if you want LLM-optimised snippets later.

### Secondary: Existing APIs (enhanced use)

- **Finnhub `/company-news`** — already available, currently used in batch. Reuse for targeted per-ticker news during research.
- **Alpha Vantage NEWS_SENTIMENT** — already available. Can be called on-demand for specific tickers.
- **SEC EDGAR FULL-TEXT SEARCH API** — free, no key needed. `https://efts.sec.gov/LATEST/search-index?q=...`

### Future: Premium Sources (Phase 2+)

- **Polygon.io** — tick-level data, insider transactions, options flow
- **Reddit/StockTwits API** — retail sentiment (noisy but occasionally signal-rich)
- **Earnings call transcripts** — via Seeking Alpha RSS or Financial Modeling Prep API

---

## Prompt Engineering: Research Mandates

### Strategy (Claude) — System Prompt Addition

```
## Research Capability

You have access to research tools. Use them to investigate specific hypotheses about the stocks you're evaluating. You are the OPPORTUNITY FINDER — your job is to build the strongest possible investment thesis.

Research guidelines:
- Search for recent news (last 7 days) for any stock where your conviction is moderate or higher
- Look for catalysts: earnings surprises, product launches, partnerships, insider buying
- Check for recent analyst upgrades or price target increases
- If a stock is in a sector under pressure, search for company-specific reasons it might outperform
- DO NOT search for every stock — focus your research budget on your top 5-7 candidates
- Always cite what you found and how it influenced your decision

You have a maximum of {max_tool_calls} research queries this cycle. Use them wisely.
```

### Skeptic (GPT-4o) — System Prompt Addition

```
## Research Capability

You have access to research tools. Use them to CHALLENGE the strategy analyst's thesis. You are the DEVIL'S ADVOCATE — your job is to find reasons the trade could fail.

Research guidelines:
- For every BUY recommendation, search for bear cases and risks
- Look for: analyst downgrades, insider selling, earnings misses, regulatory threats, competitive disruption
- Check if the strategy analyst's thesis relies on outdated or disputed information
- Search for sector-level headwinds that might not be reflected in the data
- If you find contradicting evidence, weight it heavily in your assessment
- DO NOT confirm the strategy — that's not your job. Find what could go wrong.

You have a maximum of {max_tool_calls} research queries this cycle.
```

### Risk Assessor (Gemini) — System Prompt Addition

```
## Research Capability

You have access to research tools. Use them to assess SYSTEMIC and MACRO risks that could affect the portfolio. You are the RISK ASSESSOR — your job is to evaluate whether market conditions support the proposed trades.

Research guidelines:
- Focus on macro and sector-level research, not individual stock news
- Search for: Fed policy signals, geopolitical tensions, sector rotation trends, credit market stress
- Check if multiple proposed trades have correlated risk factors
- Look for regime change signals (volatility expansion, yield curve shifts)
- Only search for individual stock risk if the position would be >10% of portfolio
- Your research should answer: "Is now the right time for this trade, given the broader environment?"

You have a maximum of {max_tool_calls} research queries this cycle.
```

---

## Implementation Phases

### Phase A — Research Tool Layer (1 session)

```
Read Claude.md and README.md.

Create the research tool layer at src/agents/research/ with:

1. tools.py — Tool definitions as provider-agnostic schemas, plus conversion
   functions to Anthropic tool format, OpenAI function format, and Google AI
   tool format. Include tool assignment map per committee member.

2. web_search.py — Brave Search API integration (env var: BRAVE_SEARCH_API_KEY).
   Returns structured results: title, url, snippet, published_date. Handles
   rate limits and timeouts gracefully.

3. news_search.py — Financial news aggregator that combines:
   - Brave Search with financial news query formatting
   - Existing Finnhub /company-news endpoint (reuse FinnhubClient)
   - Deduplication by URL/headline similarity
   Returns: headline, source, date, summary, sentiment_hint, url.

4. sec_search.py — SEC EDGAR full-text search API integration
   (https://efts.sec.gov/LATEST/search-index). No API key needed.
   Returns: filing_type, date, company, description, url.

5. cache.py — Per-cycle research cache with deterministic keying. Thread-safe.
   Shared across all committee members within a single cycle.

6. budget.py — Per-member per-cycle budget enforcement. Configurable via
   settings.yaml under research.budgets. Raises BudgetExhausted when limit hit.
   Log all budget consumption.

7. executor.py — Generic tool execution loop that:
   - Receives tool_use blocks from any LLM provider
   - Routes to the correct tool implementation
   - Enforces budget
   - Checks cache before executing
   - Logs to ResearchLog table
   - Returns formatted tool results for the provider

Add ResearchLog model to src/data/models.py. Create Alembic migration.
Add config keys under research: { enabled, budgets, brave_api_key, cache_ttl_minutes }.
Write tests for cache, budget, and tool execution with mocked API responses.

Update Claude.md and README.md.
```

### Phase B — Wire Into Strategy Engine (1 session)

```
Read Claude.md and README.md.

Modify the Strategy Engine (src/agents/strategy/engine.py) to use agentic
research via tool use.

Changes:
1. Convert the strategy LLM call from single-shot to a tool-use loop.
   Claude should be able to call search_recent_news, search_web, and
   search_sec_filings during its evaluation of each ticker.

2. Add the research mandate to the strategy system prompt (see
   docs/AGENTIC_RESEARCH_PROJECT.md for the exact prompt addition).

3. Pass the cycle's ResearchCache instance so searches are cached.

4. Enforce the strategy research budget (default: 3 calls per ticker,
   15 per cycle).

5. After the tool-use loop completes, parse the final response as before
   (StrategyDecision). The response format does not change — Claude just
   has more information when it makes the decision.

6. Log all research actions to ResearchLog table.

7. Add a feature flag: research.strategy_research_enabled (default: false).
   When false, strategy works exactly as before (no tools passed).

8. Update strategy tests to cover:
   - Tool use flow (mock tool responses)
   - Budget exhaustion mid-evaluation
   - Cache hit scenario
   - Feature flag off (legacy behavior)

Do not modify moderation yet. Update Claude.md.
```

### Phase C — Wire Into Moderation Panel (1 session)

```
Read Claude.md and README.md.

Modify the Moderation Panel (src/agents/moderation/panel.py) to give the
skeptic (GPT-4o) and risk assessor (Gemini) independent research capability.

Changes:
1. Skeptic (GPT-4o): Convert to function-calling loop with search_recent_news
   and search_web tools. Add skeptic research mandate to system prompt.
   Budget: 2 calls per ticker, 10 per cycle.

2. Risk Assessor (Gemini): Convert to tool-use loop with search_web and
   get_sector_analysis tools. Add risk assessor research mandate to system
   prompt. Budget: 1 call per ticker, 8 per cycle.

3. Both members share the same ResearchCache instance as strategy, so
   duplicate searches are served from cache.

4. The moderation output format does not change — scores, verdicts, and
   reasoning are structured the same way. The models just have more context.

5. Feature flags: research.skeptic_research_enabled,
   research.risk_assessor_research_enabled (both default: false).

6. Update moderation tests to cover tool-use flows for both members.

7. Ensure cost tracking accounts for research API costs (Brave Search)
   separately from LLM costs.

Update Claude.md and README.md.
```

### Phase D — Observability & Dashboard Integration (1 session)

```
Read Claude.md and README.md.

Add research observability to the dashboard and Slack notifications.

1. Dashboard: Add a "Research Activity" panel showing:
   - Per-cycle research summary: total searches, cache hit rate, cost
   - Per-ticker research trail: which member searched what, and what they found
   - Research influence tracking: did research change the decision vs. pre-research conviction?

2. Slack notifications: When a committee member's research changes their
   assessment, include a "Research insight" line in the Slack message.
   Example: "GPT-4o (Skeptic) found analyst downgrade from Morgan Stanley (Mar 7)
   — lowered confidence from 0.8 to 0.5"

3. Event logger: Emit research_completed events with member, ticker,
   queries_made, cache_hits, key_findings summary.

4. Add /api/research/ endpoints to dashboard backend:
   - GET /api/research/cycle/{cycle_id} — all research for a cycle
   - GET /api/research/ticker/{ticker} — research history for a ticker

Update Claude.md and README.md.
```

### Phase E — Browser Automation for Deep Web Research (1-2 sessions)

Browser Use + Playwright integration for navigating and extracting from dynamic financial websites that cannot be accessed via simple search APIs.

#### Why This Matters

Many high-value financial data sources don't have APIs or block simple scraping:
- **Seeking Alpha**: Analyst commentary, earnings call transcripts, quant ratings — behind dynamic JS rendering and login walls
- **Finviz**: Screener results, insider trading tables, analyst consensus — heavily JS-rendered
- **Company IR pages**: Every company's investor relations page has a different layout. Press releases, earnings slides, guidance updates live here
- **Morningstar**: Moat ratings, fair value estimates, stewardship grades
- **SEC EDGAR full filings**: While the search API returns metadata, reading actual filing content requires page navigation
- **Broker dashboards**: If T212 adds web features not in their API, the agent could access them programmatically

Simple web search returns headlines and snippets. Browser automation lets the agent actually *read the page* like a human analyst would — navigating to the right section, extracting structured data from tables, and following links to primary sources.

#### Architecture

```
src/agents/research/
├── ... (existing files)
├── browser_tool.py        # Browser Use integration + Playwright fallback
├── browser_config.py      # Browser session management, resource limits
└── site_recipes/          # Deterministic Playwright scripts for known sites
    ├── __init__.py
    ├── sec_edgar.py       # SEC filing page navigation
    ├── finviz.py          # Finviz screener/quote extraction
    └── seeking_alpha.py   # Seeking Alpha article extraction (if accessible)
```

#### Hybrid Strategy: Recipes First, AI Fallback

The key insight from the industry: use deterministic Playwright scripts for sites you visit frequently (predictable, fast, free), and fall back to Browser Use's AI navigation for unfamiliar or changing sites.

```python
# src/agents/research/browser_tool.py

from playwright.async_api import async_playwright
from browser_use import Agent as BrowserAgent

class BrowserResearchTool:
    """Hybrid browser tool: deterministic recipes for known sites, 
    AI-driven Browser Use for unknown sites."""
    
    # Known site recipes — fast, free, no LLM cost
    SITE_RECIPES = {
        "efts.sec.gov": "sec_edgar",
        "finviz.com": "finviz",
        "seekingalpha.com": "seeking_alpha",
    }
    
    def __init__(self, settings, research_cache, budget_tracker):
        self.settings = settings
        self.cache = research_cache
        self.budget = budget_tracker
        self._browser = None
        self._context = None
    
    async def execute(self, url: str, task: str, extract_schema: dict = None, 
                      max_steps: int = 10) -> dict:
        """Route to recipe or AI agent based on URL."""
        domain = extract_domain(url)
        
        # Check cache first
        cache_key = f"browse:{domain}:{hash(task)}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        # Try deterministic recipe first
        recipe = self.SITE_RECIPES.get(domain)
        if recipe:
            result = await self._run_recipe(recipe, url, task, extract_schema)
        else:
            # Fall back to AI-driven Browser Use
            result = await self._run_ai_browser(url, task, extract_schema, max_steps)
        
        await self.cache.set(cache_key, result)
        return result
    
    async def _run_recipe(self, recipe_name: str, url: str, task: str, 
                          schema: dict) -> dict:
        """Execute a deterministic Playwright script for a known site."""
        browser = await self._get_browser()
        page = await self._context.new_page()
        try:
            recipe_module = importlib.import_module(
                f"src.agents.research.site_recipes.{recipe_name}"
            )
            return await recipe_module.extract(page, url, task, schema)
        finally:
            await page.close()
    
    async def _run_ai_browser(self, url: str, task: str, schema: dict,
                               max_steps: int) -> dict:
        """Use Browser Use for AI-driven navigation of unknown sites."""
        self.budget.consume("browser_use", cost=0.0)  # LLM cost tracked separately
        
        agent = BrowserAgent(
            task=f"Navigate to {url}. {task}. Extract the information and return it as structured text.",
            llm=self._get_browser_llm(),  # Use cheapest capable model
            browser=await self._get_browser_use_browser(),
            max_actions=max_steps,
        )
        result = await asyncio.wait_for(agent.run(), timeout=60)
        
        return {
            "source": url,
            "method": "ai_browser",
            "content": result.extracted_content,
            "steps_taken": result.steps,
        }
    
    async def _get_browser(self):
        """Lazy-init shared Playwright browser (reused across tool calls in a cycle)."""
        if not self._browser:
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (compatible; InvestmentAgent/1.0)"
            )
        return self._browser
    
    def _get_browser_llm(self):
        """Use the cheapest capable model for browser navigation.
        Browser Use tasks are simple navigation — don't waste Sonnet on this."""
        # Gemini Flash or GPT-4o-mini are good choices for browser driving
        return ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
    
    async def cleanup(self):
        """Close browser at end of cycle. MUST be called to free memory."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
```

#### Example Site Recipe (Finviz)

```python
# src/agents/research/site_recipes/finviz.py

async def extract(page, url: str, task: str, schema: dict = None) -> dict:
    """Extract stock data from Finviz quote page.
    Deterministic — no LLM cost, ~2 seconds."""
    
    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    
    # Extract the fundamentals snapshot table
    data = {}
    rows = await page.query_selector_all("table.snapshot-table2 tr")
    for row in rows:
        cells = await row.query_selector_all("td")
        cell_texts = [await c.inner_text() for c in cells]
        # Finviz pairs: label, value, label, value, ...
        for i in range(0, len(cell_texts) - 1, 2):
            data[cell_texts[i].strip()] = cell_texts[i + 1].strip()
    
    # Extract analyst recommendations if present
    analyst_section = await page.query_selector("table.js-table-ratings")
    analyst_data = []
    if analyst_section:
        rows = await analyst_section.query_selector_all("tr")
        for row in rows[1:]:  # Skip header
            cells = await row.query_selector_all("td")
            if len(cells) >= 4:
                analyst_data.append({
                    "date": await cells[0].inner_text(),
                    "action": await cells[1].inner_text(),
                    "analyst": await cells[2].inner_text(),
                    "rating": await cells[3].inner_text(),
                })
    
    return {
        "source": url,
        "method": "recipe:finviz",
        "fundamentals": data,
        "analyst_actions": analyst_data[:5],  # Last 5 analyst actions
    }
```

#### VPS Resource Management

Your Hetzner VPS has 4GB RAM. Chromium is hungry. Resource management is critical:

```python
# src/agents/research/browser_config.py

BROWSER_RESOURCE_LIMITS = {
    # Memory management
    "max_concurrent_pages": 1,          # One page at a time on 4GB VPS
    "max_page_load_timeout_ms": 15000,  # Kill slow pages
    "max_session_duration_s": 120,      # Force cleanup after 2 min
    
    # Per-cycle limits
    "max_browser_calls_per_cycle": 5,   # Limit total browser tool uses
    "max_ai_browser_calls_per_cycle": 2, # AI Browser Use is expensive + slow
    
    # Chromium launch args (low memory mode)
    "chromium_args": [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",     # Use /tmp instead of /dev/shm
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--single-process",             # Reduce process count
        "--js-flags=--max-old-space-size=256",  # Limit V8 heap
    ],
    
    # Cleanup
    "force_cleanup_after_cycle": True,  # Always close browser after cycle ends
}
```

#### Integration with Research Tool Layer

The browser tool plugs into the existing executor from Phase A:

```python
# Addition to src/agents/research/executor.py

async def execute_tool_call(self, tool_name: str, params: dict, 
                            member: str, cycle_id: str) -> dict:
    # ... existing routing for search_web, search_recent_news, etc.
    
    if tool_name == "browse_financial_site":
        if not self.settings.research_browser_enabled:
            return {"error": "Browser research is disabled in settings"}
        
        result = await self.browser_tool.execute(
            url=params["url"],
            task=params["task"],
            extract_schema=params.get("extract_schema"),
            max_steps=params.get("max_steps", 10),
        )
        
        # Log to ResearchLog with method info
        await self._log_research(
            cycle_id=cycle_id,
            member=member,
            tool_name="browse_financial_site",
            query=f"{params['url']} — {params['task']}",
            results_summary=self._truncate(str(result), 1000),
            method=result.get("method", "unknown"),
        )
        
        return result
```

#### Lifecycle: Browser Cleanup in Orchestrator

```python
# Addition to src/orchestrator/main.py — run_cycle()

async def run_cycle(...):
    research_cache = ResearchCache(cycle_id)
    browser_tool = BrowserResearchTool(settings, research_cache, budget)
    
    try:
        # ... existing pipeline (strategy → moderation → risk → execution) ...
        # browser_tool is available to committee members via executor
        pass
    finally:
        # CRITICAL: Always clean up browser to free memory
        await browser_tool.cleanup()
        logger.info("Browser research tool cleaned up")
```

#### Claude Code Prompt — Phase E

```
Read Claude.md and README.md.

Add browser automation capability to the research tool layer for navigating
and extracting data from dynamic financial websites.

Prerequisites: Phases A-C must be complete (research tool layer, strategy
and moderation integration).

Install dependencies:
  poetry add browser-use playwright
  poetry run playwright install chromium

Create the following:

1. src/agents/research/browser_tool.py — BrowserResearchTool class with:
   - Hybrid routing: deterministic Playwright recipes for known sites,
     AI-driven Browser Use agent for unknown sites
   - Shared Playwright browser instance (lazy-init, reused within a cycle)
   - Browser Use agent using Gemini Flash as the driving model (cheapest)
   - Mandatory cleanup() method called at end of every cycle
   - Cache integration (same ResearchCache as other tools)

2. src/agents/research/browser_config.py — Resource limits configuration:
   - Max 1 concurrent page (4GB VPS constraint)
   - Max 5 browser calls per cycle, max 2 AI browser calls per cycle
   - 15s page load timeout, 120s max session duration
   - Low-memory Chromium launch args (--single-process, limited V8 heap)
   - Force cleanup after every cycle

3. src/agents/research/site_recipes/ — Deterministic Playwright scripts:
   - finviz.py: Extract fundamentals snapshot table + analyst actions
     from finviz.com/quote.ashx?t=TICKER
   - sec_edgar.py: Navigate SEC EDGAR filing pages, extract filing
     content and metadata
   - Add a base pattern so new recipes are easy to add later

4. Wire into executor.py — Route browse_financial_site tool calls through
   BrowserResearchTool. Enforce per-cycle browser budget separately from
   search budget.

5. Wire into orchestrator — Initialize BrowserResearchTool at cycle start,
   pass to executor, ensure cleanup() is called in finally block.

6. Update tool assignment — Give browse_financial_site to strategy and
   skeptic members only. Risk assessor stays macro-focused (no browser).

7. Feature flags: research.browser_enabled (default: false),
   research.ai_browser_enabled (default: false — start with recipes only).

8. Tests:
   - Recipe tests with mocked Playwright page objects
   - Browser tool routing (recipe vs AI) with mocked dependencies
   - Resource limit enforcement (max calls, timeout)
   - Cleanup verification (browser closed after cycle)
   - Integration test: full tool execution cycle with browser tool

9. Add ResearchLog entries for browser tool usage with method field
   (recipe:finviz, recipe:sec_edgar, ai_browser) for dashboard tracking.

Do NOT install Chromium in CI — tests should mock all browser interactions.
Add a pre-flight check in browser_config.py that verifies Chromium is
installed and logs a warning (not error) if missing.

Update Claude.md and README.md.
```

```yaml
research:
  enabled: true
  strategy_research_enabled: true
  skeptic_research_enabled: true
  risk_assessor_research_enabled: true

  # Data sources
  brave_search_enabled: true
  sec_search_enabled: true
  reuse_finnhub_news: true          # Use existing Finnhub client for news

  # Browser automation (Phase E)
  browser_enabled: false             # Master switch for all browser tools
  ai_browser_enabled: false          # AI-driven Browser Use (start with recipes only)
  browser_llm_model: "gemini-2.0-flash-exp"  # Cheapest model for browser driving
  max_browser_calls_per_cycle: 5     # Total browser tool calls per cycle
  max_ai_browser_calls_per_cycle: 2  # AI browser calls (more expensive/slow)
  browser_page_timeout_ms: 15000     # Kill slow page loads
  browser_session_timeout_s: 120     # Force cleanup after 2 min
  browser_cleanup_after_cycle: true  # Always close browser to free VPS memory

  # Budgets (per cycle)
  budgets:
    strategy:
      max_per_ticker: 3
      max_per_cycle: 15
      timeout_seconds: 10
    skeptic:
      max_per_ticker: 2
      max_per_cycle: 10
      timeout_seconds: 10
    risk_assessor:
      max_per_ticker: 1
      max_per_cycle: 8
      timeout_seconds: 10

  # Cache
  cache_ttl_minutes: 240            # 4 hours, aligned with cycle cache

  # Cost tracking
  brave_search_cost_per_query: 0.005  # $5/1000 queries on paid tier
  browser_use_llm_cost_per_call: 0.01 # Estimated LLM cost per AI browser navigation
  monthly_research_budget: 10.00      # GBP
```

## Environment Variables (additions)

```
BRAVE_SEARCH_API_KEY=BSA_xxx        # Brave Search API (or alternative)
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Runaway API costs from research | Medium | Medium | Per-member budgets, monthly cap, cache dedup |
| Increased cycle latency | High | Medium | Parallel tool calls, timeout enforcement, cache |
| LLM hallucinating research findings | Low | High | All research results are real API responses, not fabricated. LLM can only misinterpret, not invent sources |
| Research leading to overconfidence | Medium | Medium | Skeptic's mandate is explicitly contrarian. Risk assessor focuses on macro, not confirmation |
| Brave Search rate limits | Low | Low | Free tier is 2K/month. 3 cycles × 22 working days × ~10 searches = ~660/month. Well within limits |
| Tool-use loops not terminating | Low | High | Max iterations per member (e.g. 5), plus timeout on entire member evaluation |
| Browser Chromium memory pressure on VPS | High | Medium | Single page at a time, low-memory Chromium args, forced cleanup after every cycle, max 5 browser calls/cycle |
| AI Browser Use unpredictable navigation | Medium | Low | Capped at 2 AI browser calls/cycle, 10-step max, 60s timeout. Recipes handle known sites deterministically |
| Website layout changes breaking recipes | Medium | Low | Recipes are fallback-safe — if extraction fails, log warning and return empty. AI browser fallback available |
| Sites blocking headless Chromium | Medium | Low | Use realistic user-agent, consider Browser Use Cloud for stealth if needed. Recipes can add request headers |
| Browser tool enables scraping legal risk | Low | Medium | Only access publicly available pages. No login credential storage. Respect robots.txt in recipes. Document data source compliance |

---

## Success Metrics

After 4 weeks of operation with research enabled:

1. **Decision quality**: Do research-informed decisions have higher hit rates than pre-research baseline?
2. **Skeptic effectiveness**: Does GPT-4o find contradicting evidence that changes outcomes? Track "research-influenced downgrades"
3. **Diversity**: Measure overlap in research queries between members (should be <30% overlap)
4. **Cost efficiency**: Research cost per cycle should be <£0.50
5. **Latency impact**: Cycle time increase should be <2 minutes (from research overhead)
6. **Cache efficiency**: Cross-member cache hit rate should be >20% (indicating useful dedup without homogenising research)

---

## Relationship to Roadmap

This feature maps to **Phase 4: Signal Enhancement** in the sophistication roadmap but could be started earlier since:
- It builds on the existing macro_intelligence module (which already introduced external data into the pipeline)
- The tool-use infrastructure benefits all future enhancements (earnings calendar integration, sector rotation models, etc.)
- It directly addresses the power.ai insight about independent research curation

**Suggested roadmap placement:** After dashboard MVP (Phase 1 frontend) and before ML features (Phase 3). Label as **US-4.1: Agentic Research — Independent Tool Access for Committee Members**.

---

## Claude Code Prompt Summary

| Phase | Scope | Est. Session |
|-------|-------|-------------|
| **A** | Research tool layer + cache + budget + audit model | 1 session |
| **B** | Wire tools into Strategy Engine (Claude) | 1 session |
| **C** | Wire tools into Moderation Panel (GPT-4o + Gemini) | 1 session |
| **D** | Dashboard + Slack observability for research activity | 1 session |
| **E** | Browser automation: Playwright recipes + Browser Use AI fallback | 1-2 sessions |
