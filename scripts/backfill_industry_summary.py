#!/usr/bin/env python3
"""Backfill industry, business_summary, exchange, currency, and name for already-enriched instruments.

Targets instruments that have sector and market_cap but lack industry or business_summary
(or exchange, currency, name). Uses yfinance; rate-limited to avoid 429.

Run: poetry run python scripts/backfill_industry_summary.py
     poetry run python scripts/backfill_industry_summary.py --limit 500
     poetry run python scripts/backfill_industry_summary.py --dry-run
"""

import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
from sqlalchemy import or_

from src.data.database import get_session
from src.data.models import Instrument
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("backfill_industry")

DEFAULT_DELAY = 1.2  # seconds between requests
_rate_limit_last = 0.0
_rate_limit_lock = threading.Lock()


def _enrich_one(
    ticker: str, delay_sec: float
) -> tuple[str, str | None, str | None, str | None, str | None, str | None]:
    """Fetch industry, business_summary, exchange, currency, name from yfinance.
    Returns (ticker, industry, business_summary, exchange, currency, name)."""
    global _rate_limit_last
    with _rate_limit_lock:
        now = time.monotonic()
        wait = max(0, delay_sec - (now - _rate_limit_last))
        if wait > 0:
            time.sleep(wait)
        _rate_limit_last = time.monotonic()

    yf_symbol = t212_to_yf(ticker)
    try:
        tf = yf.Ticker(yf_symbol)
        info = tf.info
        if not info:
            return (ticker, None, None, None, None, None)
        industry = (info.get("industry") or "").strip() or None
        business_summary = (info.get("longBusinessSummary") or "").strip() or None
        exchange = (info.get("exchange") or "").strip() or None
        currency = (info.get("currency") or "").strip() or None
        name = (info.get("shortName") or info.get("longName") or "").strip()
        if name:
            name = name[:200]
        else:
            name = None
        return (ticker, industry, business_summary, exchange, currency, name)
    except Exception as e:
        logger.debug(f"yfinance failed for {ticker}: {e}")
        return (ticker, None, None, None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill industry, business_summary, exchange, currency, name for enriched instruments"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max instruments to process")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between requests (default: {DEFAULT_DELAY})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count candidates only, do not update")
    args = parser.parse_args()

    session = get_session()
    try:
        query = (
            session.query(Instrument)
            .filter(Instrument.ticker.like("%_US_EQ"))
            .filter(Instrument.data_available != False)  # noqa: E712
        )
        # Must have sector and market_cap (already enriched)
        query = query.filter(
            Instrument.sector.isnot(None),
            Instrument.sector != "",
            Instrument.sector != "Unknown",
            Instrument.market_cap.isnot(None),
            Instrument.market_cap > 0,
        )
        # Missing at least one of industry, business_summary, exchange, currency, or name
        query = query.filter(
            or_(
                Instrument.industry.is_(None),
                Instrument.industry == "",
                Instrument.business_summary.is_(None),
                Instrument.business_summary == "",
                Instrument.exchange.is_(None),
                Instrument.exchange == "",
                Instrument.currency.is_(None),
                Instrument.currency == "",
                Instrument.name.is_(None),
                Instrument.name == "",
            )
        )
        if args.limit:
            query = query.limit(args.limit)
        candidates = query.all()
    finally:
        session.close()

    total = len(candidates)
    logger.info(f"Found {total} instruments needing industry/summary/name backfill")
    if total == 0:
        return 0
    if args.dry_run:
        logger.info("Dry run: exiting without updates")
        return 0

    import time as _time
    _start = _time.monotonic()
    updated = 0
    for i, inst in enumerate(candidates):
        ticker, industry, business_summary, exchange, currency, name = _enrich_one(inst.ticker, args.delay)
        if industry or business_summary or exchange or currency or name:
            session = get_session()
            try:
                row = session.query(Instrument).filter_by(ticker=ticker).first()
                if row:
                    changed = False
                    if industry and not row.industry:
                        row.industry = industry
                        changed = True
                    if business_summary and not row.business_summary:
                        row.business_summary = business_summary
                        changed = True
                    if exchange and not row.exchange:
                        row.exchange = exchange
                        changed = True
                    if currency and not row.currency:
                        row.currency = currency
                        changed = True
                    if name and (not row.name or row.name == ticker):
                        row.name = name
                        changed = True
                    if changed:
                        row.updated_at = datetime.now(timezone.utc)
                        session.commit()
                        updated += 1
            except Exception as e:
                logger.error(f"Backfill commit failed for {ticker}: {e}")
                session.rollback()
            finally:
                session.close()
        # Log every 10 for visibility
        n = i + 1
        if n % 10 == 0:
            elapsed = _time.monotonic() - _start
            rate = n / elapsed if elapsed > 0 else 0
            eta_min = int((total - n) / rate / 60) if rate > 0 else 0
            logger.info(f"Progress: {n}/{total} | Updated: {updated} | ETA: ~{eta_min}m")

    logger.info(f"Backfill complete: {updated} instruments updated")
    return updated


if __name__ == "__main__":
    main()
