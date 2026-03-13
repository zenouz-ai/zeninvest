#!/usr/bin/env python3
"""Test Brave and Tavily + Gemini extraction of sector and market_cap."""

import json
from src.agents.market_data.brave_enrichment import (
    extract_sector_market_cap,
    extract_sector_market_cap_tavily,
)

TICKERS = ["AAPL", "MSFT", "JPM", "XOM"]

def _fmt_cap(mc) -> str:
    if mc is None:
        return "N/A"
    if mc >= 1e12:
        return f"${mc/1e12:.2f}T"
    if mc >= 1e9:
        return f"${mc/1e9:.1f}B"
    if mc >= 1e6:
        return f"${mc/1e6:.0f}M"
    return str(mc)

def main():
    print("=" * 70)
    print("Brave (Search + Answers) vs Tavily (finance topic) -> Gemini 2.5 Flash")
    print("=" * 70)
    for ticker in TICKERS:
        t212 = f"{ticker}_US_EQ"
        print(f"\n--- {ticker} ({t212}) ---")
        brave_result = extract_sector_market_cap(t212, use_search=True, use_answers=True)
        tavily_result = extract_sector_market_cap_tavily(t212)
        b = brave_result
        t = tavily_result
        print(f"  Brave:  sector={b.get('sector')!r}  market_cap={_fmt_cap(b.get('market_cap'))}  error={b.get('error')}")
        print(f"  Tavily: sector={t.get('sector')!r}  market_cap={_fmt_cap(t.get('market_cap'))}  error={t.get('error')}")
    print("\nDone.\n")

if __name__ == "__main__":
    main()
