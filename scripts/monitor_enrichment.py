#!/usr/bin/env python3
"""Monitor bulk enrichment progress every minute. Checks script status and prints stats.

Run: poetry run python scripts/monitor_enrichment.py

To run in background (logs to file):
  nohup poetry run python scripts/monitor_enrichment.py >> /tmp/enrichment_monitor.log 2>&1 &
  tail -f /tmp/enrichment_monitor.log
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_

from src.data.database import get_session
from src.data.models import Instrument


def check_bulk_running() -> bool:
    """Return True if bulk_enrich_instruments.py is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "bulk_enrich_instruments.py"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip()
    except Exception:
        return False


def get_progress() -> tuple[int, int, int, int]:
    """Return (need, enriched, total, unavailable)."""
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
        unavailable = (
            s.query(Instrument)
            .filter(Instrument.ticker.like("%_US_EQ"), Instrument.data_available == False)
            .count()
        )
        return need, enriched, total, unavailable
    finally:
        s.close()


def main() -> None:
    interval_min = 1
    interval_sec = interval_min * 60

    print("Monitoring enrichment every minute. Ctrl+C to stop.\n")

    while True:
        running = check_bulk_running()
        need, enriched, total, unavailable = get_progress()
        secs = need * 1.2
        eta = f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m" if secs >= 3600 else f"{int(secs // 60)} min"
        pct = 100 * enriched / total if total > 0 else 0

        status = "RUNNING" if running else "NOT RUNNING"
        print(f"[{time.strftime('%H:%M:%S')}] Bulk script: {status}")
        print(f"  Need: {need:,} | Enriched: {enriched:,} / {total:,} ({pct:.1f}%) | Unavail: {unavailable:,} | ETA: ~{eta}")
        if not running:
            print("  >>> Start with: nohup poetry run python scripts/bulk_enrich_instruments.py --workers 1 --delay 1.2 >> /tmp/bulk_enrich.log 2>&1 &")
        print()

        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("Stopped.")
            break


if __name__ == "__main__":
    main()
