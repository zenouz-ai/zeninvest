> **Archived 2026-03-29:** Delivered — 5,477/5,493 US equities enriched via bulk_enrich_instruments.py and backfill_industry_summary.py. See CLAUDE.md rule 5 for current enrichment architecture.

# Plan: Update ~6,900 Seed Instruments with Sector and Market Cap

## Problem

The T212-derived seed universe has ~6,900 tickers with `sector="Unknown"` and `cap_tier="mid"` (placeholder). The screener excludes `sector="Unknown"`, so none are eligible until enriched.

## Current State

- **Existing pipeline:** `enrich_instruments_batch()` runs daily at 06:00 UTC. Cascade: yfinance → Finnhub → Alpha Vantage OVERVIEW → BRAVE_ANSWERS. Saves sector, market_cap, industry, and business_summary when available.
- **Per-run limit:** 50 instruments (`batch_enrichment_per_run`).
- **Deployed (2026-03):** ~5,477 / 5,493 US equities have industry and business_summary populated (bulk + backfill). Strategy prompt uses Instrument table as fallback when yfinance returns sparse data.
- **Ticker conversion:** Use `src.utils.ticker_utils.t212_to_yf()` for consistent T212→yfinance conversion (handles class A/B, `_US_EQ`/`_UK_EQ`).

## Data Sources (Available)

| Source | Sector | Market Cap | Rate / Cost | Batch Support |
|--------|--------|------------|-------------|---------------|
| **yfinance** | Yes | Yes | Free, no formal limit | Per-ticker; can parallelize |
| **Finnhub** | Yes (finnhubIndustry) | Yes | 60/min free | Per-ticker |
| **Alpha Vantage** | Yes | Yes | 5/min free, 25/day free tier | Per-ticker |
| **Brave Answers** | Yes (extracted) | Yes | 2,000/month | Per-ticker |
| **FMP (Financial Modeling Prep)** | Yes | Yes | 250 calls/day free; batch endpoint | **Bulk** (profile-bulk) |
| **Wikipedia (S&P lists)** | Yes (GICS) | No | Free | Static file parse |

---

## Implementation Options (Prioritised)

### Option 1: One-Time Bulk Enrichment Script (Recommended First Step)

**Goal:** Enrich all 6,900 instruments in one run (or over a few hours).

**Approach:**

1. Create `scripts/bulk_enrich_instruments.py`:
   - Query instruments where `sector="Unknown"` or `market_cap` is null/0.
   - Use **parallel yfinance** (`ThreadPoolExecutor`, 10–20 workers) to fetch `Ticker.info` for sector + market_cap.
   - Batch commits every 500 updates to avoid long transactions.
   - Respect yfinance: add 0.1–0.2s delay between batches to avoid IP throttling.
   - Log progress; support `--limit N` for partial runs.
   - **Fallback:** If yfinance fails, try Finnhub (rate-limited). Skip Brave/AV for bulk (expensive).

2. **Estimated time:** ~6,900 × 0.2s ≈ 23 minutes with 20 workers (parallelism). With throttling, ~1–2 hours.

3. **Run:** `poetry run python scripts/bulk_enrich_instruments.py` (one-off or on-demand).

**Files:** `scripts/bulk_enrich_instruments.py` (implemented). Now enriches sector, market_cap, industry, business_summary, exchange, currency, name.

**Usage:**
```bash
poetry run python scripts/bulk_enrich_instruments.py
poetry run python scripts/bulk_enrich_instruments.py --limit 1000
poetry run python scripts/bulk_enrich_instruments.py --dry-run
poetry run python scripts/bulk_enrich_instruments.py --delay 2.0   # If 429 persists, wait 30–60 min first
poetry run python scripts/bulk_enrich_instruments.py --workers 1  # Sequential (default)
```

**Yahoo 429 handling:** If you see "Too Many Requests" immediately, Yahoo may have your IP in cooldown. Wait 30–60 minutes, then retry with `--delay 2.0`. Full run (~6,800 tickers) at 1.2s delay takes ~2.3 hours.

### Backfill Industry & Summary

**Goal:** Fill industry, business_summary, exchange, currency, name for instruments that already have sector+market_cap.

**Script:** `scripts/backfill_industry_summary.py`

**Usage:**
```bash
poetry run python scripts/backfill_industry_summary.py
poetry run python scripts/backfill_industry_summary.py --limit 500
poetry run python scripts/backfill_industry_summary.py --dry-run
```

Targets instruments with sector and market_cap populated but missing industry, business_summary, exchange, currency, or name. Uses yfinance; rate-limited like bulk script.

---

## Future Enrichment and Expansion

How to update, expand, or enrich the instrument dataset further:

1. **Recover gaps (16 instruments):** Re-run `backfill_industry_summary.py` without `--limit` to retry instruments that previously returned no industry/summary (yfinance may have data now).
2. **New T212 instruments:** Run `generate_seed_from_t212.py --from-db` after T212 refresh, then `bulk_enrich_instruments.py` for new tickers.
3. **Add data sources:** Extend `enrich_instruments_batch` or bulk scripts with FMP (Option 2), Wikipedia S&P lists (Option 4), or other providers when yfinance has gaps.
4. **Add fields:** To bulk-enrich additional Instrument columns (e.g. dividendYield, forwardPE), extend `_enrich_one` in bulk/backfill scripts and `_commit_batch`. Avoid time-sensitive metrics in Instrument; use per-cycle get_fundamentals for those.
5. **UK equities:** Extend bulk/backfill to `*_UK_EQ` tickers; adjust sector aliases for LSE conventions if needed.
6. **Refresh stale data:** Periodically re-run backfill for instruments where industry/summary is >12 months old (add `Instrument.updated_at` filter) to capture company changes (M&A, pivots).

---

### Option 2: Add FMP as Bulk Enrichment Source

**Goal:** Use FMP Profile Bulk API for fast batch enrichment.

**Approach:**

1. Add `FMP_API_KEY` to `.env` (free signup: https://site.financialmodelingprep.com/register).
2. Create `src/agents/market_data/fmp_client.py`:
   - `get_profiles_bulk(part: int) -> list[dict]` — FMP returns all profiles in chunks (`part=0`, `part=1`, …).
   - Map FMP `sector`, `industry`, `mktCap` to our schema.
3. Add FMP to `enrich_instruments_batch` cascade:
   - **Before** yfinance: try FMP bulk for tickers in current batch. One call can cover many.
   - Or: add `scripts/bulk_enrich_via_fmp.py` — fetch all profiles (few calls), match by ticker, update DB.
4. **Free tier:** 250 calls/day. Profile bulk returns all companies in one call per `part`. Check FMP docs for `part` count — if 1–2 calls cover all US tickers, we stay within free tier.

**Files:** `src/agents/market_data/fmp_client.py`, `config/settings.yaml` (fmp_api_key, fmp_base_url), `src/utils/config.py`, `enrich_instruments_batch` or new script.

---

### Option 3: Increase Scheduled Batch Throughput

**Goal:** Enrich faster via existing pipeline without new APIs.

**Approach:**

1. **Config changes:**
   - `batch_enrichment_per_run: 500` (from 50).
   - Add scheduler job at 06:00, 12:00, 18:00 (3×/day) instead of once.
   - Or: new job `enrich_instruments_batch` every 4 hours.
2. **Parallelise `enrich_instruments_batch`:**
   - Use `ThreadPoolExecutor` (e.g. 10 workers) for yfinance/Finnhub calls within each batch.
   - Keep cascade order (yf → Finnhub → AV → Brave) but parallelise per ticker.
3. **Time to full enrichment:** 6,900 / (500 × 3) ≈ 5 days with 3 runs/day and 500/run.

**Files:** `config/settings.yaml`, `src/scheduler/scheduler.py`, `src/agents/market_data/data_fetcher.py`.

---

### Option 4: Hybrid Seed (S&P 1500 + T212 Overflow)

**Goal:** Use known-good sector/cap for overlapping tickers; T212-only for the rest.

**Approach:**

1. Restore S&P 1500 static list (503+400+603) with real sector/cap from Wikipedia.
2. When generating seed from T212, **merge** with S&P 1500:
   - For tickers in both: use S&P sector/cap.
   - For T212-only: use Unknown/mid (enrich later).
3. Regenerate `scripts/generate_seed_from_t212.py` to output a hybrid: S&P 1500 entries first (with sector), then remaining T212 tickers (Unknown).
4. **Benefit:** ~1,400 tickers immediately usable; remaining 5,500 enrich over time.

**Files:** `scripts/generate_seed_from_t212.py`, optionally restore S&P 1500 data or fetch from Wikipedia at build time.

---

## Recommended Execution Order

1. **Option 1 (Bulk script)** — Immediate impact, no new API keys, run once.
2. **Option 3 (Increase throughput)** — Quick config + optional parallelisation; accelerates ongoing enrichment.
3. **Option 2 (FMP)** — If bulk script leaves gaps or user wants faster recurring runs.
4. **Option 4 (Hybrid seed)** — Optional; improves first-run experience.

---

## Verification

After enrichment:

```bash
# Count enriched
poetry run python -c "
from src.data.database import get_session
from src.data.models import Instrument
from sqlalchemy import or_
s = get_session()
enriched = s.query(Instrument).filter(
    Instrument.ticker.like('%_US_EQ'),
    Instrument.sector.isnot(None),
    Instrument.sector != '',
    Instrument.sector != 'Unknown',
    Instrument.market_cap.isnot(None),
    Instrument.market_cap > 0,
).count()
total_us = s.query(Instrument).filter(Instrument.ticker.like('%_US_EQ')).count()
print(f'Enriched: {enriched}/{total_us}')
s.close()
"
```

---

## Doc Updates (per CLAUDE.md)

| File | Update when |
|------|-------------|
| `CLAUDE.md` | New bulk enrichment script, FMP client, config keys |
| `docs/DATA_RATIONALE.md` | New enrichment source (FMP), bulk script |
| `config/.env.example` | `FMP_API_KEY` if Option 2 implemented |
| `README.md` | New script: `poetry run python scripts/bulk_enrich_instruments.py` |
