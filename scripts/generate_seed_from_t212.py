#!/usr/bin/env python3
"""Generate seed_universe.py from Trading 212's instrument list.

Ensures 100% match: all seed tickers are tradeable on T212.
Run with: poetry run python scripts/generate_seed_from_t212.py
          poetry run python scripts/generate_seed_from_t212.py --from-db  # use instruments table

Requires T212 API key in .env (or --from-db to use prior refresh).
"""

import argparse
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.ticker_utils import t212_to_yf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-db", action="store_true", help="Use instruments table (from prior T212 refresh) instead of API")
    args = parser.parse_args()

    if args.from_db:
        from src.data.database import get_session
        from src.data.models import Instrument
        session = get_session()
        try:
            rows = session.query(Instrument.ticker, Instrument.name, Instrument.type).filter(
                Instrument.ticker.like("%_US_EQ")
            ).all()
            # Prefer STOCK; include type=None (legacy) to maximize count
            us_stocks = [
                {"ticker": r.ticker, "name": r.name or r.ticker}
                for r in rows
                if r.type in (None, "STOCK")
            ]
        finally:
            session.close()
        print(f"Loaded {len(us_stocks)} US equities from instruments table")
    else:
        from src.agents.execution.t212_client import T212Client
        client = T212Client()
        instruments = client.get_instruments()
        client.close()
        us_stocks = [
            i
            for i in instruments
            if i.get("type") == "STOCK" and (i.get("ticker") or "").endswith("_US_EQ")
        ]
        print(f"Loaded {len(us_stocks)} US equities from T212 API")

    us_stocks.sort(key=lambda x: x.get("ticker", ""))

    entries = []
    for i in us_stocks:
        ticker = i.get("ticker", "")
        name = (i.get("name") or i.get("shortName") or ticker)[:50].replace('"', "'")
        yf = t212_to_yf(ticker)
        # sector/cap_tier: Unknown/mid — enrichment cascade fills in
        entries.append((ticker, yf, name, "Unknown", "mid"))

    # Write seed_universe.py
    out_path = Path(__file__).parent.parent / "src" / "agents" / "market_data" / "seed_universe.py"
    lines = [
        '"""Curated seed universe derived from Trading 212 instrument list.',
        "",
        "All tickers are tradeable on T212 (100% match). Sector/cap_tier start as",
        "Unknown/mid; enrichment cascade (yfinance, Finnhub, etc.) fills them in.",
        "",
        "Format: (t212_ticker, yf_ticker, name, sector, cap_tier)",
        'cap_tier: "large" = $10B+, "mid" = $2B-$10B, "small" = $300M-$2B"',
        '"""',
        "",
        "SEED_UNIVERSE: list[tuple[str, str, str, str, str]] = [",
    ]
    for t212, yf, name, sector, cap in entries:
        name_esc = name.replace('"', '\\"')
        lines.append(f'    ("{t212}", "{yf}", "{name_esc}", "{sector}", "{cap}"),')
    lines.extend([
        "]",
        "",
        "# Approximate market cap values for seeding (used only for initial population)",
        "_CAP_VALUES = {",
        '    "large": 50_000_000_000,   # $50B placeholder for large cap',
        '    "mid": 5_000_000_000,      # $5B placeholder for mid cap',
        '    "small": 1_000_000_000,    # $1B placeholder for small cap',
        "}",
        "",
        "",
        "def get_seed_instruments() -> list[dict]:",
        '    """Return seed universe as list of dicts matching Instrument model fields."""',
        "    return [",
        "        {",
        '            "ticker": t212,',
        '            "yf_ticker": yf,',
        '            "name": name,',
        '            "sector": sector,',
        '            "market_cap": _CAP_VALUES[cap_tier],',
        '            "cap_tier": cap_tier,',
        "        }",
        "        for t212, yf, name, sector, cap_tier in SEED_UNIVERSE",
        "    ]",
    ])

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(entries)} instruments to {out_path}")
    print(f"Match (seed in T212): {len(entries)} (100%)")


if __name__ == "__main__":
    main()
