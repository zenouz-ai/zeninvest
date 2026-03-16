#!/usr/bin/env python3
"""Bulk enrich instruments with sector, market cap, industry, business_summary via yfinance.

Also backfills exchange, currency, and name when Instrument fields are empty.
One-off or on-demand run. Rate-limited to avoid Yahoo Finance "Too Many Requests" / 429.

Run: poetry run python scripts/bulk_enrich_instruments.py
     poetry run python scripts/bulk_enrich_instruments.py --limit 1000
     poetry run python scripts/bulk_enrich_instruments.py --delay 1.0  # slower, safer
"""

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf

from src.agents.market_data.brave_enrichment import SECTOR_ALIASES
from src.data.database import get_session
from src.data.models import Instrument
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("bulk_enrich")

BATCH_COMMIT_SIZE = 500
UNAVAILABLE_BATCH_SIZE = 25  # Mark 404s every ~30s so "need" drops visibly
BATCH_DELAY_SEC = 0.5
DEFAULT_WORKERS = 1
DEFAULT_DELAY = 1.2  # seconds between requests; increase to 2.0 if Yahoo 429 persists

_rate_limit_lock = threading.Lock()
_rate_limit_last = 0.0


def _normalize_sector(raw: str | None) -> str | None:
    """Map raw sector string to standard sector name."""
    if not raw or not str(raw).strip():
        return None
    low = str(raw).strip().lower()
    return SECTOR_ALIASES.get(low, raw.strip())


def _is_permanent_failure(err: str) -> bool:
    """True if Yahoo will never have this symbol (404/Not Found/No fundamental data), not transient (429/500)."""
    if not err:
        return False
    low = err.lower()
    return "not found" in low or "404" in low or "quote not found" in low or "no fundamental data" in low


def _enrich_one(
    ticker: str, delay_sec: float
) -> tuple[
    str,
    str | None,
    float | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    bool,
]:
    """Fetch sector, market_cap, industry, business_summary, exchange, currency, name.
    Rate-limited. Returns (ticker, sector, market_cap, industry, business_summary,
    exchange, currency, name, mark_unavailable)."""
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
            return (ticker, None, None, None, None, None, None, None, False)
        if info.get("symbol") is None and info.get("marketCap") is None and info.get("sector") is None:
            return (ticker, None, None, None, None, None, None, None, False)
        sector_raw = info.get("sector")
        sector = _normalize_sector(sector_raw) if sector_raw and sector_raw != "Unknown" else None
        mc = info.get("marketCap")
        market_cap = int(float(mc)) if mc is not None and float(mc or 0) > 0 else None
        industry = (info.get("industry") or "").strip() or None
        business_summary = (info.get("longBusinessSummary") or "").strip() or None
        exchange = (info.get("exchange") or "").strip() or None
        currency = (info.get("currency") or "").strip() or None
        name = (info.get("shortName") or info.get("longName") or "").strip()
        if name:
            name = name[:200]  # Instrument.name limit
        else:
            name = None
        return (
            ticker,
            sector,
            market_cap,
            industry,
            business_summary,
            exchange,
            currency,
            name,
            False,
        )
    except Exception as e:
        logger.debug(f"yfinance failed for {ticker}: {e}")
        return (ticker, None, None, None, None, None, None, None, _is_permanent_failure(str(e)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk enrich instruments with sector and market cap")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max instruments to process (default: all)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS}; 1 avoids Yahoo rate limit)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between requests (default: {DEFAULT_DELAY}; increase if 429 errors)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates only, do not update",
    )
    args = parser.parse_args()

    session = get_session()
    try:
        query = (
            session.query(Instrument)
            .filter(Instrument.ticker.like("%_US_EQ"))
            .filter(
                (Instrument.sector.is_(None))
                | (Instrument.sector == "")
                | (Instrument.sector == "Unknown")
                | (Instrument.market_cap.is_(None))
                | (Instrument.market_cap == 0),
            )
            .filter(Instrument.data_available != False)  # noqa: E712
        )
        if args.limit:
            query = query.limit(args.limit)
        candidates = query.all()
    finally:
        session.close()

    total = len(candidates)
    logger.info(f"Found {total} instruments needing enrichment")
    if total == 0:
        return 0
    if args.dry_run:
        logger.info("Dry run: exiting without updates")
        return 0

    enriched = 0
    marked_unavailable = 0
    pending: list[
        tuple[
            str,
            str | None,
            float | None,
            str | None,
            str | None,
            str | None,
            str | None,
            str | None,
        ]
    ] = []
    unavailable: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_enrich_one, inst.ticker, args.delay): inst
            for inst in candidates
        }
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            ticker, sector, market_cap, industry, business_summary, exchange, currency, name, mark_unavailable = result
            if mark_unavailable:
                unavailable.append(ticker)
            if (i + 1) % 50 == 0:
                logger.info(f"Processed {i + 1}/{total} (unavailable: {len(unavailable)}, enriched batch: {enriched})")
            if sector or market_cap or industry or business_summary or exchange or currency or name:
                pending.append(
                    (ticker, sector, market_cap, industry, business_summary, exchange, currency, name)
                )
                if len(pending) >= BATCH_COMMIT_SIZE:
                    _commit_batch(pending)
                    enriched += len(pending)
                    pending = []
                    logger.info(f"Progress: {enriched} enriched, {i + 1}/{total} processed")
                    time.sleep(BATCH_DELAY_SEC)
            if len(unavailable) >= UNAVAILABLE_BATCH_SIZE:
                marked_unavailable += len(unavailable)
                _mark_unavailable_batch(unavailable)
                unavailable = []
                logger.info(f"Progress: {marked_unavailable} marked unavailable, {i + 1}/{total} processed")

    if pending:
        _commit_batch(pending)
        enriched += len(pending)
    if unavailable:
        marked_unavailable += len(unavailable)
        _mark_unavailable_batch(unavailable)

    logger.info(f"Bulk enrichment complete: {enriched} updated, {marked_unavailable} marked unavailable")
    return enriched


def _mark_unavailable_batch(tickers: list[str]) -> None:
    """Mark instruments as data_available=False so we skip them in future runs."""
    session = get_session()
    try:
        for ticker in tickers:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                inst.data_available = False
                inst.updated_at = datetime.now(timezone.utc)
        session.commit()
    except Exception as e:
        logger.error(f"Mark unavailable batch failed: {e}")
        session.rollback()
    finally:
        session.close()


def _commit_batch(
    results: list[
        tuple[
            str,
            str | None,
            float | None,
            str | None,
            str | None,
            str | None,
            str | None,
            str | None,
        ]
    ],
) -> None:
    """Commit batch of (ticker, sector, market_cap, industry, business_summary, exchange, currency, name)."""
    session = get_session()
    try:
        for ticker, sector, market_cap, industry, business_summary, exchange, currency, name in results:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                if sector and (not inst.sector or inst.sector == "Unknown"):
                    inst.sector = sector
                if market_cap and (not inst.market_cap or inst.market_cap == 0):
                    inst.market_cap = market_cap
                if industry and not inst.industry:
                    inst.industry = industry
                if business_summary and not inst.business_summary:
                    inst.business_summary = business_summary
                if exchange and not inst.exchange:
                    inst.exchange = exchange
                if currency and not inst.currency:
                    inst.currency = currency
                if name and (not inst.name or inst.name == ticker):
                    inst.name = name
                inst.updated_at = datetime.now(timezone.utc)
        session.commit()
    except Exception as e:
        logger.error(f"Batch commit failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
