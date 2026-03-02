"""Fundamental data extraction from yfinance.

Only metrics that directly influence sub-strategy scoring or risk rules are returned.
See docs/DATA_RATIONALE.md for why each metric is kept or removed.
"""

from typing import Any

import yfinance as yf

from src.utils.logger import get_logger

logger = get_logger("fundamentals")


def get_fundamentals(ticker_symbol: str) -> dict[str, Any]:
    """Extract fundamental data for a stock using yfinance.

    Returns only metrics consumed by strategies or risk rules:
    - trailing_pe: mean reversion (P/E check), factor (value score)
    - pb_ratio: factor (value score)
    - roe: factor (quality score)
    - profit_margin: factor (quality score)
    - debt_equity: mean reversion + factor (debt check, quality score)
    - earnings_growth: mean reversion (growth check)
    - earnings_momentum_qoq: factor (momentum component)
    - sector: risk manager (sector allocation cap)
    - industry: more granular than sector, used in company profiles for Claude
    - market_cap: universe ranking
    - business_summary: yfinance longBusinessSummary for qualitative LLM analysis

    Args:
        ticker_symbol: Yahoo Finance ticker (e.g., "AAPL")

    Returns:
        Dictionary of fundamental metrics.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        trailing_pe = info.get("trailingPE")
        pb_ratio = info.get("priceToBook")
        roe = info.get("returnOnEquity")
        profit_margin = info.get("profitMargins")
        debt_equity = info.get("debtToEquity")
        earnings_growth = info.get("earningsGrowth")
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "")
        market_cap = info.get("marketCap")
        business_summary = info.get("longBusinessSummary", "")

        # Earnings momentum: use quarterly income statement (Net Income)
        earnings_momentum = None
        try:
            quarterly_income = ticker.quarterly_income_stmt
            if (
                quarterly_income is not None
                and not quarterly_income.empty
                and "Net Income" in quarterly_income.index
                and quarterly_income.shape[1] >= 2
            ):
                recent = float(quarterly_income.loc["Net Income"].iloc[0])
                previous = float(quarterly_income.loc["Net Income"].iloc[1])
                if previous != 0:
                    earnings_momentum = (recent - previous) / abs(previous)
        except Exception:
            pass

        return {
            "trailing_pe": _safe_float(trailing_pe),
            "pb_ratio": _safe_float(pb_ratio),
            "roe": _safe_float(roe),
            "profit_margin": _safe_float(profit_margin),
            "debt_equity": _safe_float(debt_equity),
            "earnings_growth": _safe_float(earnings_growth),
            "earnings_momentum_qoq": _safe_float(earnings_momentum),
            "sector": sector,
            "industry": industry,
            "market_cap": _safe_float(market_cap),
            "business_summary": business_summary,
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
