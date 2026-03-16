#!/usr/bin/env python3
"""Quick progress check for bulk enrichment. Run: poetry run python scripts/check_enrichment_progress.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_

from src.data.database import get_session
from src.data.models import Instrument


def main() -> None:
    s = get_session()
    try:
        need = (
            s.query(Instrument)
            .filter(
                Instrument.ticker.like("%_US_EQ"),
                Instrument.data_available != False,
                or_(
                    Instrument.sector.is_(None),
                    Instrument.sector == "",
                    Instrument.sector == "Unknown",
                    Instrument.market_cap.is_(None),
                    Instrument.market_cap == 0,
                ),
            )
            .count()
        )
        enriched = (
            s.query(Instrument)
            .filter(
                Instrument.ticker.like("%_US_EQ"),
                Instrument.sector.isnot(None),
                Instrument.sector != "Unknown",
                Instrument.market_cap > 0,
            )
            .count()
        )
        total = s.query(Instrument).filter(Instrument.ticker.like("%_US_EQ")).count()
        unavail = (
            s.query(Instrument)
            .filter(Instrument.ticker.like("%_US_EQ"), Instrument.data_available == False)
            .count()
        )

        secs = need * 1.2
        mins = secs / 60
        eta = f"{int(mins // 60)}h {int(mins % 60)}m" if mins >= 60 else f"{int(mins)} min"

        print(f"Need enrichment:  {need:,}")
        print(f"Enriched so far:  {enriched:,} / {total:,}")
        print(f"Marked unavailable (404): {unavail:,}")
        print(f"Estimated ETA:    ~{eta} (at 1.2s/ticker)")
    finally:
        s.close()


if __name__ == "__main__":
    main()
