# Data Pipeline Rationale

Every data point in the investment agent pipeline must justify its existence by demonstrably
influencing a trading decision. This document maps each data point to its decision path,
explains how it alters outcomes, and flags data that has been removed for not earning its place.

**Principle:** A simpler model with fewer, well-understood inputs outperforms a complex model
overloaded with noise. Every field must answer: "How does this change what we buy or sell?"

---

## Decision Paths

Data influences the final trading decision through four paths:

1. **Sub-strategy scoring** → Strategy reasoning text → Claude prompt → Claude decision
2. **LLM prompt context** → Claude/GPT-4o/Gemini interprets directly
3. **Hard risk rules** → APPROVE / REJECT / RESIZE (overrides LLM decisions)
4. **Audit trail** → Trade journals, database records (no decision influence)

Only paths 1-3 matter for decision quality. Path 4 is for post-hoc analysis only.

---

## 1. OHLCV Data (yfinance)

| Field | Source | Refresh | Decision Path | Influence |
|-------|--------|---------|---------------|-----------|
| Open | yfinance `download()` | 12h cycle | None directly | Intermediate for indicator calc |
| High | yfinance `download()` | 12h cycle | Path 1 | Feeds Bollinger Bands |
| Low | yfinance `download()` | 12h cycle | Path 1 | Feeds Bollinger Bands |
| Close | yfinance `download()` | 12h cycle | Path 1 | Core input for all indicators |
| Volume | yfinance `download()` | 12h cycle | **NONE** | Fetched but never used |

**Period:** 1 year daily (needed for 200-day MA calculation, ~252 trading days).

**Rationale:** OHLCV is the foundation of technical analysis. Close prices drive RSI, MACD,
moving averages, and Bollinger Bands. High/Low feed Bollinger Bands. Volume is not currently
used — a potential future enhancement for confirming price moves, but omitting it keeps the
model simpler.

---

## 2. Technical Indicators

### KEPT — Directly influence sub-strategy scoring

| Indicator | Strategy | How It Alters Decisions | Score Impact |
|-----------|----------|------------------------|--------------|
| `rsi_14` | Momentum | RSI 50-70 = +25 (sweet spot). RSI >80 = SELL trigger. | Up to ±25 points |
| `rsi_14` | Mean Rev | RSI <30 = +30 (oversold BUY). RSI >60 = SELL exit. | Up to +30 points |
| `macd_histogram` | Momentum | Positive histogram = +10 (bullish confirmation). | +10 points |
| `macd_bullish_crossover` | Momentum | True = +25 (strong BUY signal). | +25 points |
| `macd_bearish_crossover` | Momentum | True = SELL trigger for existing holdings. | Triggers SELL |
| `above_50ma` | Momentum | True = +25, also required for BUY action. | +25 + gate |
| `below_lower_bb` | Mean Rev | True = +25 (price at statistical extreme). | +25 points |
| `current_price` | Mean Rev | Compared to MA-20 for exit signal. | Triggers SELL |
| `ma_20` | Mean Rev | Price reaching MA-20 = SELL exit for mean rev trades. | Triggers SELL |

### REMOVED — Never consumed by any strategy or rule

| Indicator | Why Removed |
|-----------|-------------|
| `macd_line` | Intermediate value. Only the crossover booleans and histogram are consumed. |
| `macd_signal` | Intermediate value. Same as above. |
| `bb_upper` | Never read by any strategy. The `below_lower_bb` boolean is what matters. |
| `bb_middle` | Never read by any strategy. |
| `bb_lower` | Intermediate. Only `below_lower_bb` boolean is consumed. |
| `bb_pct` | Never read anywhere in the codebase. |
| `ma_50` | Intermediate. Only `above_50ma` boolean is consumed. |
| `ma_200` | Only used to compute golden/death cross, which were also unused. |
| `above_200ma` | No strategy references this. `above_50ma` is the active signal. |
| `golden_cross` | Occurs once every few years. Never used in any scoring logic. |
| `death_cross` | Same as golden cross — too rare and never used. |
| `atr_14` | Average True Range. Not used in any strategy, risk rule, or prompt. |

**Simplification rationale:** Reducing from 20 to 8 output fields. The removed indicators
were computed but never read, creating a false sense of thoroughness. The 8 kept indicators
fully cover the three active strategies (momentum, mean reversion, factor via relative strength).

---

## 3. Fundamental Data (yfinance)

### KEPT — Influence strategy scoring or risk rules

| Metric | Strategy | How It Alters Decisions |
|--------|----------|------------------------|
| `trailing_pe` | Mean Rev | P/E >50 = fundamental_ok=False (0.3x penalty). P/E < sector avg = +15. |
| `trailing_pe` | Factor | P/E <15 = +30 value. P/E >40 = -20 value. |
| `pb_ratio` | Factor | P/B <1.5 = +20 value. P/B >10 = -15 value. |
| `roe` | Factor | ROE >20% = +25 quality. ROE <0 = -20 quality. |
| `profit_margin` | Factor | Margin >20% = +15 quality. Margin <0 = -15 quality. |
| `debt_equity` | Mean Rev | D/E >1.5 = fundamental_ok=False (0.3x penalty). |
| `debt_equity` | Factor | D/E <0.5 = +15 quality. D/E >2.0 = -15 quality. |
| `earnings_growth` | Mean Rev | Growth >0 = +10. Growth < -20% = fundamental_ok=False. |
| `earnings_momentum_qoq` | Factor | QoQ momentum >10% = +15 momentum component. |
| `sector` | Risk Mgr | Sector allocation cap (35%). Used for diversification checks. |
| `market_cap` | Universe | Used to rank/filter instrument universe (top 200 by cap). |

### REMOVED — Never consumed by any strategy or rule

| Metric | Why Removed |
|--------|-------------|
| `forward_pe` | Never read by any strategy. Same API call as trailing_pe (zero cost to fetch), but including unused data adds noise to the pipeline. |
| `revenue_growth_yoy` | Never read by any strategy. Earnings_growth serves the same purpose. |
| `industry` | Never read. `sector` is used for risk rules; industry adds no decision value. |

---

## 4. Macro Data

### KEPT — Influence market regime or risk rules

| Metric | Decision Path | How It Alters Decisions |
|--------|---------------|------------------------|
| `vix` | Path 2 + 3 | Risk rules: VIX >25 caps positions at 8%; >35 caps at 5%. Passed to Claude for context. Used in market regime classification (>30 = BEAR). |
| `sp500_above_200ma` | Path 1 | Key input to market regime: below 200MA = BEAR signal. |
| `sp500_pct_above_200ma` | Path 4 | Audit context in trade journals. |
| `market_regime` | Path 2 | BULL/BEAR/SIDEWAYS label passed directly to Claude. Influences overall positioning and risk appetite in LLM reasoning. |

### REMOVED — Computed but never used in any decision

| Metric | Why Removed |
|--------|-------------|
| `yield_spread_10y_short` | Computed from ^TNX minus ^IRX, but never used in market regime classification or any other decision logic. The market regime is determined solely by VIX and S&P vs 200MA. Also, ^IRX is the 3-month T-Bill rate, not the 2-year yield — the proxy was inaccurate for yield curve inversion detection. |
| `ten_year_yield` | Intermediate value, only existed to compute the yield spread. |
| `short_yield` | Intermediate value, only existed to compute the yield spread. |

**Note:** Yield curve data could be reintroduced if the market regime logic is enhanced to
use it. Currently, the simpler VIX + S&P 200MA approach is sufficient and avoids the
inaccurate ^IRX proxy.

---

## 5. Finnhub Data (Analyst + Insider)

### KEPT

| Data | Decision Path | How It Alters Decisions |
|------|---------------|------------------------|
| Analyst recommendations (buy/hold/sell counts) | Path 2 | Passed as JSON to Claude prompt. Claude can see analyst consensus and weigh it against technical signals. Also passed to moderators (GPT-4o, Gemini) for independent review. |
| Analyst consensus (BUY/HOLD/SELL) | Path 2 | Summary label derived from recommendation counts. |
| Insider sentiment (MSPR score) | Path 2 | Monthly Purchase/Sale Ratio. Positive = insiders buying. Passed to Claude and moderators. Academic research shows insider buying has mild predictive value. |

### REMOVED

| Data | Why Removed |
|------|-------------|
| `get_peers()` | Method existed but was never called from any pipeline stage. Dead code. |

**Refresh:** Per-cycle (12h). Rate limited at 60 req/min. Up to 15 tickers per cycle × 2 calls
(recommendations + insider) = 30 Finnhub calls per cycle.

---

## 6. Alpha Vantage Data (News Sentiment)

### KEPT — All data serves the LLM prompt path

| Data | Decision Path | How It Alters Decisions |
|------|---------------|------------------------|
| Broad market sentiment (economy, earnings, tech) | Path 2 | 50 articles with AI sentiment scores. Formatted as headline summaries with sentiment labels. Gives Claude and moderators context on market mood that technical indicators cannot capture. |
| Ticker-specific sentiment | Path 2 | Top articles for the 15 candidate tickers. Per-ticker sentiment scores let Claude correlate news with technical signals. |
| **Per-ticker news extraction** | Path 2 | `extract_per_ticker_news()` parses each article's `ticker_sentiments` array to build per-stock summaries. Each ticker gets its own section: avg sentiment score, bullish/bearish counts, and top 5 articles sorted by relevance. Claude sees which news belongs to which stock — no more generic "no specific news" fallbacks. |
| Aggregate stats (bullish/bearish/neutral counts) | Path 2 | Quick summary metrics at top of news section in prompt. |

**Format for LLM (per-ticker):**
```
**AAPL**:
Ticker avg sentiment: +0.250 (Bullish: 3, Bearish: 0, Articles: 5)
  [Bullish +0.250] Apple Reports Strong Q4 Earnings (Reuters)
  [Somewhat-Bearish -0.100] Tech Sector Faces Headwinds (Bloomberg)
```

**Format for LLM (broad):** Each article distilled to one line: `[Bullish +0.234] Headline text (Source)`.
This is an efficient format — compact enough for token budget, rich enough for LLM reasoning.

**Refresh:** 3 API calls per cycle (broad + ticker summary + raw articles for per-ticker parsing).
Free tier: 25 calls/day. Two 12h cycles = 6 calls/day, well within limits.

---

## 7. Relative Strength (Custom Calculation)

| Data | Decision Path | How It Alters Decisions |
|------|---------------|------------------------|
| 6-month RS vs S&P 500 | Path 1 | Momentum: RS >1.0 = +25 (outperforming market). Factor momentum component: RS >1.1 = +20. A stock outperforming the benchmark has demonstrated relative strength. |

**Calculation:** `(1 + stock_6mo_return) / (1 + benchmark_6mo_return)`. RS > 1.0 means the
stock outperformed the S&P 500 over 6 months.

---

## 8. How the LLM Uses Each Data Section

### Claude (Strategy Synthesis)

The Claude prompt contains these sections and this is how each should influence decisions:

| Prompt Section | What Claude Sees | Expected Influence |
|----------------|------------------|--------------------|
| Portfolio State | JSON: cash, positions, returns | Position sizing, rebalancing needs |
| Market Regime | BULL/BEAR/SIDEWAYS | Overall risk appetite — fewer/smaller buys in BEAR |
| Momentum Proposals | `TICKER: BUY (score: 75) — reasoning` | Strong momentum (>60) should increase conviction |
| Mean Reversion Proposals | `TICKER: BUY (score: 70) — reasoning` | Oversold stocks with good fundamentals |
| Factor Proposals | `TICKER: composite=72 (V=65 Q=80 M=70)` | Multi-factor quality ranking of top stocks |
| Analyst Data | JSON: buy/hold/sell counts, insider MSPR | Confirmation or warning signal |
| Per-Ticker News | Per-stock sentiment scores + headlines from AV | Specific catalysts/risks per stock (not a combined dump) |
| Broad Market Sentiment | Aggregate headlines + sentiment | Overall market mood beyond numbers |
| Risk Budget | VIX, cash %, position limits | Constrains position sizing |

### GPT-4o (Skeptic Moderator)

Receives the full market context via `market_context` dict (see context.py):
- **Trade proposal** — Claude's decision with conviction, reasoning, action, allocation
- **Portfolio context** — Current cash, positions, returns
- **Technical indicators** — RSI, MACD histogram/crossovers, Bollinger Band, MAs
- **Fundamentals** — P/E, P/B, ROE, margins, debt, earnings trajectory
- **Market conditions** — VIX (with severity label), regime, S&P 500 trend
- **Sub-strategy signals** — Momentum, mean reversion, and factor scores with reasoning
- **Analyst data** — Finnhub recommendation counts, consensus, insider MSPR
- **Per-ticker news** — Alpha Vantage per-stock sentiment scores + headlines (not a combined dump)
- **Strategy Agent's Market Assessment** — Claude's overall market thesis, presented with the instruction "Challenge this thesis — do you agree with the reasoning?"

Role: Challenge assumptions, identify recency bias, flag risks. When sub-strategies
conflict or news contradicts the thesis, GPT-4o should DISAGREE or MODIFY.

### Gemini (Risk Assessor)

Receives the same full market context as GPT-4o, including Claude's strategy assessment.
Scores each trade on three dimensions (growth 1-10, risk 1-10, confidence 1-10) using
quantitative data. Flags trades where risk > growth. Gemini's scoring guidelines map
specific data ranges to score adjustments (e.g., VIX >25 adds 1-2 risk points,
D/E >2.0 raises risk by 2-3 points).

### Data Flow to Moderators (context.py)

The `format_market_context()` function in `src/agents/moderation/context.py` formats
the raw `market_context` dict into a readable, token-efficient string with labeled sections.
Both moderators receive identical data, ensuring independent reviews are based on the same
information. Key formatting features:
- RSI labels: oversold (<30), overbought (>70), neutral
- VIX labels: low (<15), normal (15-20), elevated (20-30), high (30-35), extreme (>35)
- Bollinger Band: "Yes (oversold)" when below lower band
- MACD crossover: "Bullish crossover (buy signal)" / "Bearish crossover (sell signal)"
- Strategy assessment: Claude's market thesis is shown under "Strategy Agent's Market Assessment" with a prompt to challenge it

---

## 9. Decision to Keep Three Strategies vs. Simplifying

The three sub-strategies (Momentum, Mean Reversion, Factor) serve different market conditions:
- **Momentum** works in trending markets (BULL regime)
- **Mean Reversion** works in volatile/oversold conditions
- **Factor** provides a baseline quality filter regardless of regime

A single strategy would miss opportunities in different regimes. However, the weights
(35/30/35) are fixed and never adapt to market conditions. A potential future enhancement
would be regime-dependent weighting.

---

## 10. LLM Necessity Assessment: Do We Need LLMs at All?

### What could be done with pure mathematical rules (no LLM)

The three sub-strategies are already 100% rule-based. A purely mathematical system could:

1. **Generate candidates** — Sub-strategies already score stocks 0-100 using fixed rules
2. **Select trades** — Pick top N stocks by composite score above a threshold
3. **Size positions** — Fixed allocation formula (e.g., `score / 100 * max_position_pct`)
4. **Apply risk rules** — The 10 hard rules (VIX caps, sector limits, drawdown) are already mathematical

**What this system would look like:**
- BUY: Top 5 stocks with composite score >65, all sub-strategies non-negative
- SELL: Any holding where momentum score <30 or RSI >80
- Position size: `min(score * 0.1, max_position_pct)`
- Cost: $0/cycle (no API calls beyond data fetching)

### What LLMs add that rules cannot replicate

| Capability | Rules-Based | LLM-Based | Delta |
|-----------|-------------|-----------|-------|
| **Signal synthesis** | Fixed weighted average of 3 scores | Contextual weighting — can increase momentum weight in BULL, reduce in BEAR | LLM adapts to regime |
| **News interpretation** | Cannot process text | Reads headlines, identifies catalysts/risks, adjusts conviction | Unique capability |
| **Conflicting signal resolution** | Always uses fixed formula | Can reason: "momentum is strong but earnings declining, reduce position" | LLM applies judgment |
| **Contrarian reasoning** | Cannot go against consensus | Can identify when analyst consensus is wrong based on technical deterioration | Adds edge cases |
| **Portfolio-level thinking** | Each stock scored independently | Can consider correlations: "already heavy in tech, skip this tech stock" | Holistic view |
| **Narrative generation** | Cannot produce reasoning | Provides tradeable thesis with catalysts, risks, exit conditions | Audit + learning |

### Assessment

**The LLM adds meaningful value in three areas:**

1. **News integration** — This is the strongest justification. No mathematical rule can extract
   meaning from "Company X announces 3:1 stock split" or "FDA rejects drug application".
   News is inherently unstructured and requires language understanding.

2. **Signal conflict resolution** — When momentum says BUY (score: 75) but factor says LOW
   (score: 35), a fixed formula produces a middling score (~55) regardless of context. The LLM
   can reason about WHY they conflict and make a nuanced decision.

3. **Dynamic risk calibration** — The LLM can tighten position sizes during earnings season
   or geopolitical events even if VIX hasn't moved yet. Rules react; LLMs can anticipate.

**The LLM adds marginal value in:**

4. **Portfolio-level thinking** — Could be replaced by correlation-based rules, but the LLM's
   natural language reasoning is more flexible.

5. **Moderation** — The 3-way committee catches errors the primary analyst makes, but the
   cost is 3x the LLM calls. The conviction-based fallback (no moderators + conviction >85)
   shows the system works without them.

**Conclusion:** LLMs are necessary for news interpretation and nuanced signal synthesis.
However, the sub-strategies themselves should remain rule-based — LLMs should not replace
the scoring logic, only sit on top of it as a synthesis and sanity-check layer.

---

## 11. Paid vs. Local/Free Models Assessment

### Current cost structure (per cycle)

| Model | Role | Approx. Tokens | Approx. Cost/Cycle |
|-------|------|---------------|-------------------|
| Claude Sonnet 3.5 | Strategy synthesis | ~4K in / ~2K out | ~$0.03 |
| GPT-4o | Skeptic moderator | ~2K in / ~0.5K out per trade (×3-5 trades) | ~$0.02-0.05 |
| Gemini Flash 2.0 | Risk assessor | ~2K in / ~0.5K out per trade (×3-5 trades) | ~$0.001-0.003 |
| **Total** | | | **~$0.05-0.08/cycle** |

With 2 cycles/day: **$0.10-0.16/day** or **$3-5/month**.

### Could local/free models replace paid ones?

| Requirement | Local LLM (Llama 3, Mistral) | Paid API (Claude, GPT-4o, Gemini) |
|------------|------------------------------|-----------------------------------|
| **JSON reliability** | Inconsistent. Requires heavy prompt engineering and retry logic. | High. Claude/GPT-4o reliably produce valid JSON with simple instructions. |
| **Financial reasoning** | Adequate for simple analysis. Weak on nuanced multi-factor trade-offs. | Strong. Trained on financial data, can reference market conventions. |
| **News comprehension** | Adequate for sentiment classification. Weak on complex causation. | Strong. Can identify 2nd-order effects (e.g., rate hike → housing → REITs). |
| **Latency** | Fast locally (~2-5s on good GPU). Slow on CPU (~30-60s). | 1-3s API round-trip. Consistent. |
| **Infra cost** | Free inference but requires GPU server. A decent GPU (4090) = $200+/month cloud. | $3-5/month for this use case. |
| **Deployment** | Complex. Model updates, quantization, memory management. | Simple. API key + SDK. |

### Recommendation

**Keep paid models. The cost is negligible ($3-5/month) and the reliability is critical.**

- **Claude Sonnet for strategy** — The most important decision point. Requires strong reasoning
  and reliable JSON output. Local models cannot match this reliably. Cost: ~$1.50/month.
- **GPT-4o for skeptic moderation** — Provides genuine independent viewpoint (different training,
  different biases). Replacing with a local model would not add diversity. Cost: ~$1-2/month.
- **Gemini Flash for risk scoring** — Already the cheapest model. Effectively free at
  ~$0.05/month. No reason to replace.

**Cost-optimization opportunity:** If costs need to be reduced, the first target should be
reducing the number of moderation calls (e.g., only moderate BUY trades with conviction <80),
not switching to cheaper models. The conviction-based bypass already saves money when
moderators are unavailable.

**Local model viable only if:** The system were running 100+ cycles/day (quant-style), making
API costs $100+/month. At 2 cycles/day, the $3-5/month cost does not justify the complexity
and reliability tradeoff of local deployment.

---

## 12. Changelog

| Date | Change | Rationale |
|------|--------|-----------|
| 2026-02-26 | Removed 12 unused indicator outputs | Never consumed by any strategy. Reduced noise. |
| 2026-02-26 | Removed forward_pe, revenue_growth_yoy, industry | Never consumed. Zero API cost savings but cleaner data. |
| 2026-02-26 | Removed yield spread (^TNX - ^IRX) from macro | Never used in market regime or any decision. Proxy was inaccurate. |
| 2026-02-26 | Removed get_peers() from Finnhub client | Dead code, never called. |
| 2026-02-26 | Enhanced Claude prompt with interpretation guidance | LLM had no instructions on how to weight data sections. |
| 2026-02-26 | Enriched moderator data: full market context | GPT-4o and Gemini previously received only Finnhub analyst JSON + truncated news. Now receive indicators, fundamentals, macro, sub-strategy signals, analyst data, and full news sentiment. |
| 2026-02-26 | Created context.py shared formatter | Centralised moderator data formatting with labeled sections, severity labels (RSI, VIX), and signal annotations. |
| 2026-02-26 | Enhanced moderator prompts with scoring guidelines | Both moderators now have explicit instructions on how to interpret RSI ranges, P/E thresholds, VIX levels, and sub-strategy disagreements. |
| 2026-02-26 | Added LLM necessity assessment (Section 10) | Documented where LLMs add value vs. where mathematical rules suffice. Conclusion: LLMs necessary for news interpretation and signal synthesis, not for scoring. |
| 2026-02-26 | Added paid vs. local models assessment (Section 11) | At $3-5/month, paid models are cheaper than local GPU infrastructure and more reliable. No change recommended. |
| 2026-02-27 | Added per-ticker news extraction from Alpha Vantage | `extract_per_ticker_news()` parses AV `ticker_sentiments` to build per-stock summaries. Claude now sees which news belongs to which stock. Eliminates generic "no specific news" fallbacks. |
| 2026-02-27 | Added strategy_assessment to moderator context | Claude's `market_assessment` thesis is now passed to GPT-4o and Gemini so moderators can challenge the overall market reasoning, not just individual trade proposals. |
| 2026-02-27 | Added universe screening with sector/cap diversity | `get_screened_universe()` samples candidates across sectors (min 3 per sector) and market-cap tiers (40% large, 35% mid, 25% small). System can now discover new stocks beyond existing positions. |
| 2026-02-27 | Added `enrich_instrument_metadata()` | Back-fills sector and market_cap from yfinance into the instruments table, improving future screening cycles. |
| 2026-02-27 | Fixed REDUCE action in order manager | REDUCE now correctly negates quantity (partial sell). Previously would have tried to BUY instead. Risk manager also checks `min_positions` for REDUCE. |
| 2026-02-27 | Added automatic stop-loss orders after BUY | `place_stop_loss()` uses T212's stop order API (GTC validity) with Claude's `stop_loss_pct`. Placed automatically after successful BUY executions. |
| 2026-02-27 | Added 72-hour screening cooldown | `last_screened_at` column on Instrument table. Screened stocks are excluded from future screens for 72 hours (configurable via `screening_cooldown_hours`), preventing the same candidates from appearing in consecutive cycles. |
