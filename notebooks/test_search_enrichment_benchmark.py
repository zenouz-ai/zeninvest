#!/usr/bin/env python3
"""Benchmark: BRAVE_SEARCH vs BRAVE_ANSWERS vs TAVILY — cost, time, accuracy.

Ground truth: yfinance fundamentals.
"""

import time
from src.agents.market_data.brave_enrichment import (
    extract_sector_market_cap_brave_search,
    extract_sector_market_cap_brave_answers,
    extract_sector_market_cap_tavily,
)
from src.agents.market_data.fundamentals import get_fundamentals

TICKERS = ["AAPL", "MSFT", "JPM", "XOM", "NVDA"]

# Sector alias for comparison (yfinance vs our normalized names)
YF_SECTOR_MAP = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financial Services": "Financial Services",
    "Financials": "Financial Services",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Basic Materials": "Basic Materials",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
}


def get_ground_truth(symbol: str) -> dict:
    """Fetch sector and market_cap from yfinance."""
    f = get_fundamentals(symbol)
    sector = f.get("sector") or "Unknown"
    sector = YF_SECTOR_MAP.get(sector, sector)
    mc = f.get("market_cap")
    return {"sector": sector, "market_cap": mc}


def sector_match(pred: str | None, truth: str) -> bool:
    """True if predicted sector matches truth (case-insensitive, normalized)."""
    if not pred:
        return False
    return pred.strip().lower() == truth.strip().lower()


def market_cap_ok(pred: int | None, truth: float | None, tol_pct: float = 25) -> bool:
    """True if predicted market_cap within tol_pct of truth."""
    if truth is None or truth <= 0:
        return pred is None  # no ground truth
    if pred is None:
        return False  # failed to extract when truth exists
    ratio = pred / truth
    return 1 - tol_pct / 100 <= ratio <= 1 + tol_pct / 100


def run_one(source: str, ticker: str, extract_fn, truth: dict) -> dict:
    """Run extraction, return metrics."""
    t212 = f"{ticker}_US_EQ"
    metrics: dict = {}
    t0 = time.perf_counter()
    result = extract_fn(t212, metrics_out=metrics)
    elapsed = time.perf_counter() - t0

    sector_ok = sector_match(result.get("sector"), truth["sector"])
    cap_ok = market_cap_ok(result.get("market_cap"), truth.get("market_cap"))

    return {
        "source": source,
        "ticker": ticker,
        "sector": result.get("sector"),
        "market_cap": result.get("market_cap"),
        "error": result.get("error"),
        "time_sec": round(elapsed, 2),
        "cost_gbp": metrics.get("cost_gbp", 0.0),
        "sector_match": sector_ok,
        "market_cap_match": cap_ok,
    }


def main():
    print("=" * 72)
    print("BENCHMARK: BRAVE_SEARCH | BRAVE_ANSWERS | TAVILY")
    print("Metrics: cost (Gemini £), time (sec), sector accuracy, market_cap accuracy")
    print("Ground truth: yfinance. Cost = Gemini only (Brave/Tavily have own limits).")
    print("=" * 72)

    # Ground truth
    truths = {}
    for t in TICKERS:
        g = get_ground_truth(t)
        truths[t] = g
        mc = g.get("market_cap")
        mc_str = f"${mc/1e12:.2f}T" if mc and mc >= 1e12 else (f"${mc/1e9:.1f}B" if mc else "N/A")
        print(f"\n{t}: truth sector={g['sector']!r} market_cap={mc_str}")

    sources = [
        ("BRAVE_SEARCH", extract_sector_market_cap_brave_search),
        ("BRAVE_ANSWERS", extract_sector_market_cap_brave_answers),
        ("TAVILY", extract_sector_market_cap_tavily),
    ]

    all_results: list[dict] = []

    for source_name, extract_fn in sources:
        print(f"\n--- {source_name} ---")
        for ticker in TICKERS:
            r = run_one(source_name, ticker, extract_fn, truths[ticker])
            all_results.append(r)
            mc = r.get("market_cap")
            mc_str = f"${mc/1e9:.0f}B" if mc and mc >= 1e9 else (str(mc) if mc else "N/A")
            ok = "✓" if r["sector_match"] and r["market_cap_match"] else ("s" if r["sector_match"] else "c" if r["market_cap_match"] else "✗")
            print(f"  {ticker}: sector={r['sector']!r} cap={mc_str} time={r['time_sec']}s cost=£{r['cost_gbp']:.4f} {ok}")

    # Summary
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for source_name, _ in sources:
        subset = [r for r in all_results if r["source"] == source_name]
        total_time = sum(r["time_sec"] for r in subset)
        total_cost = sum(r["cost_gbp"] for r in subset)
        sector_ok = sum(1 for r in subset if r["sector_match"])
        cap_ok = sum(1 for r in subset if r["market_cap_match"])
        both_ok = sum(1 for r in subset if r["sector_match"] and r["market_cap_match"])
        n = len(subset)
        print(f"{source_name}: time={total_time:.1f}s total cost=£{total_cost:.4f} | sector {sector_ok}/{n} cap {cap_ok}/{n} both {both_ok}/{n}")
    print()

if __name__ == "__main__":
    main()
