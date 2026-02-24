"""Fundamental data extraction from yfinance."""

from typing import Any

import yfinance as yf

from src.utils.logger import get_logger

logger = get_logger("fundamentals")


def get_fundamentals(ticker_symbol: str) -> dict[str, Any]:
    """Extract fundamental data for a stock using yfinance.

    Args:
        ticker_symbol: Yahoo Finance ticker (e.g., "AAPL")

    Returns:
        Dictionary of fundamental metrics.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        pb_ratio = info.get("priceToBook")
        roe = info.get("returnOnEquity")
        profit_margin = info.get("profitMargins")
        debt_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        earnings_growth = info.get("earningsGrowth")
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        market_cap = info.get("marketCap")

        # Earnings momentum: try to get quarterly earnings
        earnings_momentum = None
        try:
            quarterly_earnings = ticker.quarterly_earnings
            if quarterly_earnings is not None and len(quarterly_earnings) >= 2:
                recent = quarterly_earnings.iloc[-1].get("Earnings", 0)
                previous = quarterly_earnings.iloc[-2].get("Earnings", 0)
                if previous != 0:
                    earnings_momentum = (recent - previous) / abs(previous)
        except Exception:
            pass

        return {
            "trailing_pe": _safe_float(trailing_pe),
            "forward_pe": _safe_float(forward_pe),
            "pb_ratio": _safe_float(pb_ratio),
            "roe": _safe_float(roe),
            "profit_margin": _safe_float(profit_margin),
            "debt_equity": _safe_float(debt_equity),
            "revenue_growth_yoy": _safe_float(revenue_growth),
            "earnings_growth": _safe_float(earnings_growth),
            "earnings_momentum_qoq": _safe_float(earnings_momentum),
            "sector": sector,
            "industry": industry,
            "market_cap": _safe_float(market_cap),
        }

    except Exception as e:
        logger.error(f"Failed to get fundamentals for {ticker_symbol}: {e}")
        return {"error": str(e), "sector": "Unknown"}


def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float, returning None if not possible."""
    if val is None:
        return None
    try:
        result = float(val)
        if result != result:  # NaN check
            return None
        return result
    except (ValueError, TypeError):
        return None
