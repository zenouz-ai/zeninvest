---
tags: [investment-agent, data, pipeline, rationale]
status: active
last_updated: 2026-03-29
---

# Data Pipeline Rationale

Every data point must justify its existence by demonstrably influencing a trading decision. A simpler model with fewer, well-understood inputs outperforms a complex model overloaded with noise.

## Decision Paths

Data influences trades through 5 paths:

1. **Sub-strategy scoring** → rule-based scores feed Claude's synthesis
2. **LLM prompt context** → Claude, GPT-4o, Gemini interpret directly
3. **Hard risk rules** → deterministic APPROVE/REJECT/RESIZE
4. **UOV optimizer** → cross-cycle ranking and queueing
5. **Audit trail** → journals and DB records (no decision influence)

Only paths 1–4 matter for decision quality.

## What We Keep and Why

**OHLCV** (yfinance, 1yr daily) — foundation for all technical indicators. Volume is fetched but deliberately unused — simplicity over false thoroughness.

**8 Technical Indicators** (from an original 20):
- RSI 14 — momentum sweet spot (50–70) and mean reversion oversold (<30)
- MACD histogram + crossovers — bullish/bearish confirmation
- Above 50-day MA — momentum gate
- Below lower Bollinger Band — statistical extreme signal
- Current price vs MA-20 — mean reversion exit

12 indicators removed (MACD line/signal, BB upper/middle/lower/pct, MA-50/200, above_200ma, golden/death cross, ATR-14) because they were computed but never consumed by any strategy or rule.

**9 Fundamentals** (yfinance) — P/E, P/B, ROE, profit margin, D/E, earnings growth, earnings momentum, sector, market cap. Each directly feeds a sub-strategy or risk rule.

**Company Profiles** — industry label + longBusinessSummary (~300 chars) from yfinance. Enables Claude to reason about moats, regulatory exposure, macro news impact. Persisted in Instrument; ~5,477 instruments enriched via bulk/backfill scripts.

**Macro Data** — VIX (risk rules + regime), S&P vs 200MA (regime classification), market_regime (BULL/BEAR/SIDEWAYS → Claude prompt). Yield spread removed — proxy was inaccurate and never used.

**Macro Intelligence** — sector performance from AV SECTOR (fallback: yfinance SPDR ETFs) and economic headlines from Finnhub /news. Enables "fundamentally strong but sector headwind — defer buy." Cached 4h.

**Finnhub** — analyst buy/hold/sell counts, insider sentiment (MSPR). Per-cycle. Deferred to active-review tickers when intraday. get_peers() removed (dead code).

**Alpha Vantage** — broad market sentiment + per-ticker sentiment. `extract_per_ticker_news()` parses ticker_sentiments for per-stock summaries. 2 API calls/cycle, cached 4h.

**Agentic Research** (US-4.4) — Brave (primary) + Tavily (fallback) + SEC EDGAR (free). 5 tools: web_search, news_search, sector_search, sec_search, macro_search. 35 calls/cycle max across all committee members. Deduped by (ticker, tool, query). All three pipeline members (Strategy, Skeptic, Risk) have full tool-use loops with per-member caps (20/8/7).

## Three Strategies, Fixed Weights

- **Momentum** (35%) — works in trending/BULL markets
- **Mean Reversion** (30%) — works in volatile/oversold conditions
- **Factor** (35%) — baseline quality filter regardless of regime

Weights are static. Regime-dependent weighting is a planned enhancement (US-2.2).

## LLM Necessity Assessment

LLMs add genuine value in: (1) news interpretation — no rule can parse "FDA rejects drug application," (2) signal conflict resolution — when momentum says BUY but factor says LOW, context matters, (3) dynamic risk calibration — anticipating risks before VIX moves.

LLMs add marginal value in portfolio-level thinking (correlation rules could suffice) and moderation (3x cost, but conviction-based fallback works without it).

Sub-strategies should stay rule-based. LLMs synthesise on top.

## Cost of Paid vs Local Models

At $3–7/month, paid APIs are cheaper than local GPU infra ($200+/month cloud GPU) and far more reliable for JSON output. No reason to switch unless running 100+ cycles/day.

## Architectural Decisions

- **2026-02-26** — Reduced indicators from 20 to 8. Removed 12 that were computed but never consumed.
- **2026-02-26** — Removed yield spread from macro data. Inaccurate proxy, never used.
- **2026-02-27** — Added per-ticker news extraction from Alpha Vantage. Claude now sees which news belongs to which stock.
- **2026-03-06** — Added company profiles (industry + business_summary) to Claude prompt.
- **2026-03-06** — Added macro intelligence (sector performance + economic headlines).
- **2026-03-13** — Expanded seed from ~160 to ~6900 (T212-derived). Bulk enrichment via yfinance.
- **2026-03-20** — Agentic research (US-4.4): 5 tools across all 3 committee members, shared pipeline budget.
- **2026-03-25** — Volume signals (US-4.1): OBV + 20-day volume ratio in indicator output; surfaced in momentum/mean-reversion scoring and moderator context.
- **2026-03-27** — Correlation screening enhancements (US-3.3) and earnings calendar integration (US-4.2) on roadmap for future data enrichment.

## Related Notes

- [[Multi-LLM Pipeline Architecture]]
- [[Risk and Governance Framework]]
- [[Project Overview]]
