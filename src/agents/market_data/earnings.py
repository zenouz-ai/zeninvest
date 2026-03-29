"""Per-ticker earnings context helpers for entry-quality guardrails."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from src.utils.logger import get_logger
from src.utils.market_holidays import is_us_market_holiday

logger = get_logger("earnings")


def default_earnings_context() -> dict[str, Any]:
    """Return the empty earnings-context payload."""
    return {
        "next_earnings_date": None,
        "trading_days_to_earnings": None,
        "earnings_imminent": False,
        "recent_earnings_date": None,
        "recent_earnings_surprise_pct": None,
        "post_earnings_drift_active": False,
        "post_earnings_drift_bias": "unknown",
        "post_earnings_price_change_pct": None,
    }


def get_earnings_context(
    ticker_symbol: str,
    *,
    price_history: pd.DataFrame | None = None,
    now: date | None = None,
    pre_window_trading_days: int = 5,
    post_window_trading_days: int = 10,
) -> dict[str, Any]:
    """Fetch upcoming-earnings and recent post-earnings-drift context."""
    context = default_earnings_context()
    today = now or date.today()

    try:
        ticker = yf.Ticker(ticker_symbol)
        next_earnings_date = _extract_next_earnings_date(ticker.calendar)
        if next_earnings_date is not None:
            days_to_earnings = count_trading_days_until(today, next_earnings_date)
            context["next_earnings_date"] = next_earnings_date.isoformat()
            context["trading_days_to_earnings"] = days_to_earnings
            context["earnings_imminent"] = (
                days_to_earnings is not None and 0 <= days_to_earnings <= pre_window_trading_days
            )

        recent_earnings = _extract_recent_earnings_row(ticker, today)
        if recent_earnings is None:
            return context

        recent_date, recent_row = recent_earnings
        context["recent_earnings_date"] = recent_date.isoformat()
        context["recent_earnings_surprise_pct"] = _extract_surprise_pct(recent_row)

        trading_days_since = count_trading_days_between(recent_date, today)
        if trading_days_since is None or trading_days_since > post_window_trading_days:
            return context

        context["post_earnings_drift_active"] = True
        price_change_pct = _compute_post_earnings_price_change_pct(
            price_history=price_history,
            earnings_date=recent_date,
        )
        context["post_earnings_price_change_pct"] = price_change_pct
        context["post_earnings_drift_bias"] = _classify_drift_bias(
            surprise_pct=context["recent_earnings_surprise_pct"],
            price_change_pct=price_change_pct,
        )
        return context
    except Exception as exc:
        logger.warning("Failed to fetch earnings context for %s: %s", ticker_symbol, exc)
        return context


def count_trading_days_until(start_date: date, end_date: date) -> int | None:
    """Count US trading days from the day after start_date through end_date inclusive."""
    if end_date < start_date:
        return None
    count = 0
    cursor = start_date
    while cursor < end_date:
        cursor += timedelta(days=1)
        if _is_trading_day(cursor):
            count += 1
    return count


def count_trading_days_between(start_date: date, end_date: date) -> int | None:
    """Count US trading days from the day after start_date through end_date inclusive."""
    return count_trading_days_until(start_date, end_date)


def _extract_next_earnings_date(calendar_data: Any) -> date | None:
    if not calendar_data:
        return None
    if isinstance(calendar_data, dict):
        raw = calendar_data.get("Earnings Date")
        if isinstance(raw, list) and raw:
            raw = raw[0]
        return _normalize_to_date(raw)
    return None


def _extract_recent_earnings_row(
    ticker: yf.Ticker,
    today: date,
) -> tuple[date, pd.Series | dict[str, Any]] | None:
    try:
        earnings_dates = ticker.get_earnings_dates(limit=6)
    except ImportError as exc:
        logger.info("Recent earnings history unavailable without lxml: %s", exc)
        return None
    except Exception as exc:
        logger.info("Recent earnings history unavailable: %s", exc)
        return None

    if earnings_dates is None or getattr(earnings_dates, "empty", True):
        return None

    for idx, row in earnings_dates.iterrows():
        earnings_date = _normalize_to_date(idx)
        if earnings_date is None or earnings_date > today:
            continue
        return earnings_date, row
    return None


def _extract_surprise_pct(row: pd.Series | dict[str, Any]) -> float | None:
    if isinstance(row, pd.Series):
        data = row.to_dict()
    else:
        data = dict(row)

    for key, value in data.items():
        label = str(key).strip().lower()
        if "surprise" in label:
            parsed = _safe_float(value)
            if parsed is not None:
                return parsed

    actual = None
    estimate = None
    for key, value in data.items():
        label = str(key).strip().lower()
        if "reported eps" in label or "actual" in label:
            actual = _safe_float(value)
        elif "estimate" in label:
            estimate = _safe_float(value)

    if actual is None or estimate in (None, 0):
        return None
    return ((actual - estimate) / abs(estimate)) * 100.0


def _compute_post_earnings_price_change_pct(
    *,
    price_history: pd.DataFrame | None,
    earnings_date: date,
) -> float | None:
    if price_history is None or price_history.empty or "Close" not in price_history:
        return None

    closes = price_history["Close"]
    history = closes.dropna()
    if history.empty:
        return None

    normalized_index = [_normalize_to_date(idx) for idx in history.index]
    indexed_rows = [
        (idx_date, float(value))
        for idx_date, value in zip(normalized_index, history.tolist(), strict=False)
        if idx_date is not None
    ]
    if not indexed_rows:
        return None

    entry_price = None
    latest_price = indexed_rows[-1][1]
    for idx_date, value in indexed_rows:
        if idx_date >= earnings_date:
            entry_price = value
            break

    if entry_price in (None, 0):
        return None
    return ((latest_price - entry_price) / entry_price) * 100.0


def _classify_drift_bias(
    *,
    surprise_pct: float | None,
    price_change_pct: float | None,
) -> str:
    if surprise_pct is None or price_change_pct is None:
        return "unknown"
    if surprise_pct > 0 and price_change_pct > 0:
        return "positive"
    if surprise_pct < 0 and price_change_pct < 0:
        return "negative"
    if surprise_pct == 0 or price_change_pct == 0:
        return "neutral"
    return "mixed"


def _normalize_to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.date()
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
        if parsed != parsed:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _is_trading_day(value: date) -> bool:
    return value.weekday() < 5 and not is_us_market_holiday(value)
