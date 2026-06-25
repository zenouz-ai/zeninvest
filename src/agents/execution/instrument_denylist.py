"""Time-bounded BUY denial list for broker-rejected instruments (P4-4, US-7.5).

When Trading 212 rejects a BUY with a client error (HTTP 400/403), re-attempting the
same ticker every cycle wastes an API call and repeats the failure. This module records
such rejections in ``halted_instruments`` with a TTL (default 24h) and exposes a
pre-flight ``is_halted`` check so the pipeline skips those tickers until the window
expires. BUY-only: SELLs and protective stops are never blocked. Restart-safe
(persisted to SQLite, architecture rule #9). Kill switch:
``order_management.instrument_denylist_enabled``.
"""

from datetime import datetime, timedelta, timezone

from src.data.database import get_session, write_transaction
from src.data.models import HaltedInstrument
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("instrument_denylist")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly naive DB timestamp to aware UTC for comparison."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def record_rejection(
    ticker: str,
    status_code: int | None,
    reason: str,
    *,
    ttl_hours: int | None = None,
    last_error: str | None = None,
) -> None:
    """Upsert a ticker onto the BUY denial list, extending its TTL window."""
    settings = get_settings()
    if not settings.instrument_denylist_enabled:
        return
    if ttl_hours is None:
        ttl_hours = settings.instrument_denylist_ttl_hours
    now = _now()
    halted_until = now + timedelta(hours=ttl_hours)
    try:
        with write_transaction() as session:
            row = session.query(HaltedInstrument).filter_by(ticker=ticker).first()
            if row is None:
                session.add(
                    HaltedInstrument(
                        ticker=ticker,
                        reason=reason,
                        status_code=status_code,
                        halted_at=now,
                        halted_until=halted_until,
                        hit_count=1,
                        last_error=(last_error or "")[:2000] or None,
                    )
                )
            else:
                row.reason = reason
                row.status_code = status_code
                row.halted_until = halted_until
                row.hit_count = (row.hit_count or 0) + 1
                if last_error:
                    row.last_error = last_error[:2000]
        logger.warning(
            "Denylisted %s for %sh (status=%s, reason=%s)",
            ticker,
            ttl_hours,
            status_code,
            reason,
        )
    except Exception as exc:  # fail-open: a denylist write must never break execution
        logger.warning("Failed to record denylist rejection for %s: %s", ticker, exc)


def is_halted(ticker: str) -> bool:
    """Return True if the ticker has an unexpired BUY halt (and the feature is on)."""
    settings = get_settings()
    if not settings.instrument_denylist_enabled:
        return False
    session = get_session()
    try:
        row = session.query(HaltedInstrument).filter_by(ticker=ticker).first()
        if row is None:
            return False
        halted_until = _as_utc(row.halted_until)
        return halted_until is not None and halted_until > _now()
    except Exception as exc:  # fail-open: never block execution on a read error
        logger.debug("Denylist read failed for %s, treating as not halted: %s", ticker, exc)
        return False
    finally:
        session.close()


def active_halts() -> list[HaltedInstrument]:
    """Return all currently-unexpired halt rows (for status/dashboard surfacing)."""
    session = get_session()
    try:
        now = _now()
        rows = session.query(HaltedInstrument).all()
        return [r for r in rows if (_as_utc(r.halted_until) or now) > now]
    finally:
        session.close()


def active_halt_count() -> int:
    """Count of currently-unexpired halts (cheap helper for cycle summaries)."""
    return len(active_halts())


def clear(ticker: str) -> bool:
    """Manually remove a ticker from the denial list. Returns True if a row was removed."""
    with write_transaction() as session:
        row = session.query(HaltedInstrument).filter_by(ticker=ticker).first()
        if row is None:
            return False
        session.delete(row)
    logger.info("Cleared denylist entry for %s", ticker)
    return True


def clear_expired() -> int:
    """Delete rows whose halt window has elapsed. Returns count removed."""
    now = _now()
    with write_transaction() as session:
        rows = session.query(HaltedInstrument).all()
        stale = [r for r in rows if (_as_utc(r.halted_until) or now) <= now]
        for row in stale:
            session.delete(row)
        count = len(stale)
    if count:
        logger.info("Cleared %d expired denylist entr%s", count, "y" if count == 1 else "ies")
    return count
