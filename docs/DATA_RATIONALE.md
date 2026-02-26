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
| Aggregate stats (bullish/bearish/neutral counts) | Path 2 | Quick summary metrics at top of news section in prompt. |

**Format for LLM:** Each article distilled to one line: `[Bullish +0.234] Headline text (Source)`.
This is an efficient format — compact enough for token budget, rich enough for LLM reasoning.

**Refresh:** 2 API calls per cycle (broad + ticker batch). Free tier: 25 calls/day.
Two 12h cycles = 4 calls/day, well within limits.

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
| News Sentiment | Headlines with sentiment scores | Catalysts, risks, market mood |
| Risk Budget | VIX, cash %, position limits | Constrains position sizing |

### GPT-4o (Skeptic Moderator)

Receives the trade proposal + portfolio context + sentiment data. Expected to challenge
assumptions, identify recency bias, and flag risks the primary analyst missed.

### Gemini (Risk Assessor)

Receives the same data. Expected to score growth potential vs risk level and flag trades
where risk exceeds growth.

---

## 9. Decision to Keep Three Strategies vs. Simplifying

The three sub-strategies (Momentum, Mean Reversion, Factor) serve different market conditions:
- **Momentum** works in trending markets (BULL regime)
- **Mean Reversion** works in volatile/oversold conditions
- **Factor** provides a baseline quality filter regardless of regime

A single strategy would miss opportunities in different regimes. However, the weights
(35/30/35) are fixed and never adapt to market conditions. A potential future enhancement
would be regime-dependent weighting.

The multi-LLM committee (Claude + GPT-4o + Gemini) adds cost and latency but provides
independent verification. The fallback logic (conviction thresholds when moderators are
unavailable) shows the system can function with fewer LLMs. Monitoring should track whether
moderation actually prevents bad trades or just adds cost.

---

## 10. Changelog

| Date | Change | Rationale |
|------|--------|-----------|
| 2026-02-26 | Removed 12 unused indicator outputs | Never consumed by any strategy. Reduced noise. |
| 2026-02-26 | Removed forward_pe, revenue_growth_yoy, industry | Never consumed. Zero API cost savings but cleaner data. |
| 2026-02-26 | Removed yield spread (^TNX - ^IRX) from macro | Never used in market regime or any decision. Proxy was inaccurate. |
| 2026-02-26 | Removed get_peers() from Finnhub client | Dead code, never called. |
| 2026-02-26 | Enhanced Claude prompt with interpretation guidance | LLM had no instructions on how to weight data sections. |
