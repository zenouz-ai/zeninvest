---
tags: [dashboard, macro, world-news, headlines]
status: delivered
last_updated: 2026-03-29
---

# World News Dashboard Tab

> **Status:** Active | **User stories:** US-1.7.4 (delivered)
> **Depends on:** [PROACTIVE_MACRO_NEWS_INTELLIGENCE.md](PROACTIVE_MACRO_NEWS_INTELLIGENCE.md) for backend system design and MacroState/MacroSignalLog schema.
> **Related:** [DASHBOARD.md](DASHBOARD.md)

Persistent macro-economic headline archive and regime display for the dashboard.

## Purpose

Surface macro-economic news headlines, regime classification, and portfolio implications in a dedicated "World News" dashboard tab. Provides transparency into the macro context that influences trading decisions.

## Data Sources

No additional APIs, LLMs, Brave, or Tavily are required. All data comes from existing sources:

| Source | Data | Cost | Frequency |
|--------|------|------|-----------|
| Finnhub `/news` (general) | Economic headlines (Fed, tariffs, earnings, inflation, etc.) | Free tier (60/min) | Every analysis cycle |
| Alpha Vantage SECTOR | S&P 500 sector performance | 1 API call (existing) | Every analysis cycle |
| yfinance SPDR ETFs | Fallback sector data | Free | When AV fails |
| VIX + S&P 500 200MA | Regime indicators | Free (yfinance) | Every analysis cycle |

## Architecture

### Headline Persistence

Previously, Finnhub headlines were cached in `NewsSentimentCache` with a 4-hour TTL and then discarded. The World News feature adds persistent archival:

1. **`MacroHeadline` table** — permanent archive of all fetched headlines with deduplication
2. **`persist_headlines()`** — called after each macro intelligence fetch in `DataFetcher`
3. **`categorize_headline()`** — keyword-based category assignment (fed, rates, trade, earnings, inflation, jobs, gdp, market, general)
4. Deduplication via unique constraint on `(headline, published_at)`

### Regime Data

Uses existing `MacroState` and `MacroSignalLog` tables from US-4.5 (Proactive Macro Intelligence). When the proactive scan is enabled, daily snapshots include regime, confidence, top signals, and action plan. The World News page displays this data directly.

### Backend API

| Endpoint | Description |
|----------|-------------|
| `GET /api/macro/state` | Latest proactive macro state (regime, confidence, signals, action plan) |
| `GET /api/macro/state/history?days=7` | Regime timeline for the past N days |
| `GET /api/macro/headlines?days=7&category=all` | Archived headlines, optionally filtered by category |
| `GET /api/macro/signals?days=7` | Macro signal audit trail |
| `GET /api/macro/summary` | Compact summary for Dashboard Home card |

### Frontend

- **World News page** (`/world-news`) — 5 sections: Current Regime, Regime Timeline, Headlines Feed, Action Plan, Sector Snapshot
- **Dashboard Home card** — compact macro conditions bar with regime badge, confidence, top signal, headline count, link to World News
- Navigation: "World News" in the "More" dropdown (secondary nav)

## News Amalgamation

Headlines are grouped and summarised deterministically — no LLM required:

1. **Group by date** — daily buckets with expandable sections
2. **Group by category** — keyword-derived categories (Fed, Rates, Trade, Earnings, Inflation, Jobs, GDP, Market, General)
3. **Count by category** — category_counts in summary endpoint shows topic intensity
4. **Regime context** — regime timeline shows how conditions changed alongside headlines
5. **"What it means"** — deterministic action plan (portfolio_bias, sector_implications, risks, opportunities) from `MacroState`

## Configuration

```yaml
# config/settings.yaml
macro:
  persist_headlines: true          # Archive Finnhub headlines to macro_headlines table
  proactive_scan_enabled: false    # Enable daily regime snapshots (required for regime/action plan display)
```

## Database Model

```
MacroHeadline (macro_headlines)
├── id: Integer PK
├── headline: Text (not null)
├── source: String(100) (e.g. "Reuters", "CNBC")
├── published_at: DateTime (indexed)
├── url: Text (nullable)
├── category: String(50) (indexed — fed, rates, trade, earnings, inflation, jobs, gdp, market, general)
├── fetched_at: DateTime
├── cycle_id: String(100) (nullable)
└── UNIQUE(headline, published_at) — dedup constraint
```

## Graceful Degradation

- **No MacroState data** (proactive scan disabled): Regime section shows guidance to enable `macro.proactive_scan_enabled`
- **No headlines** (`persist_headlines: false`): Headlines section shows guidance to enable the setting
- **Both disabled**: Page still renders with empty states and configuration guidance

## Testing

- 14 new tests in `tests/test_macro_intelligence.py` (categorisation + persistence)
- 9 new tests in `tests/test_dashboard_macro.py` (API endpoints)
- Total: 524 tests passing
