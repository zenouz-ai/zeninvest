"""Macro-level market intelligence for trading decisions.

Gathers:
1. Sector-level sentiment and trend data (e.g. tech sector downtrend, energy rotation)
2. Key economic news (Fed decisions, tariffs, earnings seasons)
3. Structured output for committee decision process — e.g. "AAPL fundamentally strong
   but sector headwind — defer buy"

Data sources:
- Alpha Vantage SECTOR: Real-time S&P 500 sector performance (1 API call)
- yfinance SPDR ETFs: Fallback when Alpha Vantage fails (rate limit, error)
- Finnhub /news: General market news for economic headlines (free tier, 60/min)
"""

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
from src.agents.market_data.finnhub_client import FinnhubClient
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("macro_intelligence")

# SPDR sector ETFs for yfinance fallback (maps AV sector name -> ticker)
AV_SECTOR_TO_ETF: dict[str, str] = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Communication Services": "XLC",
    "Energy": "XLE",
    "Real Estate": "XLRE",
    "Consumer Discretionary": "XLY",
}

# Map yfinance/fundamentals sector names to Alpha Vantage SECTOR keys
# Alpha Vantage: Information Technology, Health Care, Consumer Discretionary, etc.
# yfinance: Technology, Healthcare, Consumer Cyclical, etc.
YF_TO_AV_SECTOR: dict[str, str] = {
    "Technology": "Information Technology",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials",
    "Basic Materials": "Materials",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
}


def get_sector_performance(alpha_vantage: AlphaVantageClient) -> dict[str, Any]:
    """Fetch S&P 500 sector performance from Alpha Vantage SECTOR API.

    Returns dict with sector performance percentages (real-time, 1d, 5d, 1m)
    and derived trend labels (outperform / underperform / neutral).
    """
    result: dict[str, Any] = {"sectors": {}, "error": None}

    try:
        data = alpha_vantage.get_sector_performance()

        if "error" in data:
            result["error"] = data.get("error", "Unknown error")
            return result

        # Alpha Vantage returns: Rank A: Real-Time Performance, Rank B: 1 Day, etc.
        real_time = data.get("Rank A: Real-Time Performance", {})
        one_day = data.get("Rank B: 1 Day Performance", {})
        five_day = data.get("Rank C: 5 Day Performance", {})
        one_month = data.get("Rank D: 1 Month Performance", {})

        for sector_name, rt_str in real_time.items():
            try:
                rt_pct = _parse_pct(rt_str)
                d1_pct = _parse_pct(one_day.get(sector_name, "0%"))
                d5_pct = _parse_pct(five_day.get(sector_name, "0%"))
                m1_pct = _parse_pct(one_month.get(sector_name, "0%"))
            except (ValueError, TypeError):
                continue

            # Trend: underperform if negative on multiple horizons
            trend = "neutral"
            if rt_pct < -0.5 and (d5_pct < 0 or m1_pct < 0):
                trend = "underperform"
            elif rt_pct > 0.5 and (d5_pct > 0 or m1_pct > 0):
                trend = "outperform"

            result["sectors"][sector_name] = {
                "real_time_pct": rt_pct,
                "1d_pct": d1_pct,
                "5d_pct": d5_pct,
                "1m_pct": m1_pct,
                "trend": trend,
            }

        return result

    except Exception as e:
        logger.warning(f"Alpha Vantage SECTOR fetch failed: {e}")
        result["error"] = str(e)
        return result


def _parse_pct(value: Any) -> float:
    """Parse percentage string like '2.50%' or '-1.20%' to float."""
    if value is None:
        return 0.0
    s = str(value).strip().replace("%", "").replace(",", "")
    return float(s) if s else 0.0


def get_sector_performance_yfinance() -> dict[str, Any]:
    """Fallback: derive sector performance from SPDR sector ETFs via yfinance.

    Used when Alpha Vantage SECTOR fails (rate limit, error). No API key needed.
    Returns same structure as get_sector_performance for compatibility.
    """
    result: dict[str, Any] = {"sectors": {}, "error": None, "source": "yfinance"}

    try:
        tickers = list(AV_SECTOR_TO_ETF.values())
        df = yf.download(tickers, period="1mo", progress=False, auto_adjust=True)

        if df.empty or len(df) < 2:
            result["error"] = "Insufficient OHLCV data for sector ETFs"
            return result

        # Flatten MultiIndex: (Close, XLK) -> Close_XLK
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [f"{c[0]}_{c[1]}" if isinstance(c, tuple) and len(c) == 2 else str(c) for c in df.columns]

        for sector_name, ticker in AV_SECTOR_TO_ETF.items():
            close_col = f"Close_{ticker}" if f"Close_{ticker}" in df.columns else "Close"
            if close_col not in df.columns:
                continue
            closes = df[close_col].dropna()
            if len(closes) < 2:
                continue

            # % change: 1d (last 2 rows), 5d (last 6), 1m (full)
            last = float(closes.iloc[-1])
            prev_1d = float(closes.iloc[-2])
            prev_5d = float(closes.iloc[-6]) if len(closes) >= 6 else prev_1d
            prev_1m = float(closes.iloc[0])

            rt_pct = 100 * (last - prev_1d) / prev_1d if prev_1d else 0.0
            d5_pct = 100 * (last - prev_5d) / prev_5d if prev_5d else 0.0
            m1_pct = 100 * (last - prev_1m) / prev_1m if prev_1m else 0.0

            trend = "neutral"
            if rt_pct < -0.5 and (d5_pct < 0 or m1_pct < 0):
                trend = "underperform"
            elif rt_pct > 0.5 and (d5_pct > 0 or m1_pct > 0):
                trend = "outperform"

            result["sectors"][sector_name] = {
                "real_time_pct": rt_pct,
                "1d_pct": rt_pct,
                "5d_pct": d5_pct,
                "1m_pct": m1_pct,
                "trend": trend,
            }

        return result

    except Exception as e:
        logger.warning(f"yfinance sector fallback failed: {e}")
        result["error"] = str(e)
        return result


def get_economic_headlines(finnhub: FinnhubClient, limit: int = 10) -> dict[str, Any]:
    """Fetch general market news from Finnhub for economic context.

    Returns headlines relevant to Fed, tariffs, earnings, macro events.
    """
    result: dict[str, Any] = {"headlines": [], "error": None}

    try:
        data = finnhub.get_market_news(category="general")

        if not data:
            return result

        keywords = [
            "fed", "fomc", "rate", "tariff", "earnings", "inflation", "gdp",
            "jobs", "employment", "cpi", "ppi", "treasury", "china", "trade",
        ]
        scored: list[tuple[float, dict]] = []

        for item in data[:limit * 2]:  # Oversample to filter
            headline = (item.get("headline") or item.get("title") or "").lower()
            summary = (item.get("summary") or "").lower()
            text = f"{headline} {summary}"
            score = sum(1 for k in keywords if k in text)
            if score > 0 or len(scored) < limit:
                scored.append((score, {
                    "headline": item.get("headline") or item.get("title", "N/A"),
                    "source": item.get("source", "N/A"),
                    "datetime": item.get("datetime"),
                    "url": item.get("url"),
                }))

        scored.sort(key=lambda x: (-x[0], x[1]["datetime"] or 0), reverse=True)
        result["headlines"] = [s[1] for s in scored[:limit]]

        # Simple earnings season heuristic: check if "earnings" appears frequently
        earnings_count = sum(1 for s in scored if "earnings" in (s[1].get("headline") or "").lower())
        result["earnings_season_flag"] = earnings_count >= 2

        return result

    except Exception as e:
        logger.warning(f"Finnhub news fetch failed: {e}")
        result["error"] = str(e)
        return result


def get_macro_intelligence(
    alpha_vantage: AlphaVantageClient,
    finnhub: FinnhubClient,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Fetch and combine sector performance + economic headlines.

    Returns structured dict for committee decision process:
    - sector_trends: per-sector performance and trend labels
    - economic_highlights: key headlines (Fed, tariffs, earnings)
    - sector_headwind(sector): helper to check if a sector has headwind
    """
    if not enabled:
        return {
            "enabled": False,
            "sector_trends": {},
            "economic_highlights": "",
            "sectors": {},
            "headlines": [],
        }

    sector_data = get_sector_performance(alpha_vantage)
    sectors = sector_data.get("sectors", {})

    # Fallback to yfinance SPDR ETFs when Alpha Vantage fails (rate limit, error)
    sector_errors: list[str] = [e for e in [sector_data.get("error")] if e]
    if not sectors and get_settings().data_providers.get("sector_fallback_yfinance", True):
        fallback = get_sector_performance_yfinance()
        if fallback.get("sectors"):
            sectors = fallback["sectors"]
            sector_data = fallback
            logger.info("Using yfinance sector fallback (Alpha Vantage unavailable)")
        elif fallback.get("error"):
            sector_errors.append(f"Fallback: {fallback['error']}")

    headline_data = get_economic_headlines(finnhub, limit=8)
    headlines = headline_data.get("headlines", [])

    # Build economic highlights summary for LLM consumption
    lines: list[str] = []
    for h in headlines[:5]:
        lines.append(f"- {h.get('headline', 'N/A')} ({h.get('source', 'N/A')})")
    economic_highlights = "\n".join(lines) if lines else "No major economic headlines."

    # Build sector trends summary
    sector_lines: list[str] = []
    for name, data in sectors.items():
        rt = data.get("real_time_pct", 0)
        trend = data.get("trend", "neutral")
        sector_lines.append(f"- {name}: {rt:+.2f}% ({trend})")
    sector_summary = "\n".join(sector_lines) if sector_lines else "Sector data unavailable."

    return {
        "enabled": True,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sector_trends": sectors,
        "sector_summary": sector_summary,
        "economic_highlights": economic_highlights,
        "headlines": headlines,
        "earnings_season_flag": headline_data.get("earnings_season_flag", False),
        "errors": sector_errors + [e for e in [headline_data.get("error")] if e],
    }


def get_sector_headwind(macro_intel: dict[str, Any], yf_sector: str) -> str | None:
    """Return headwind message if the given sector is underperforming, else None.

    Use this to flag stocks as 'fundamentally strong but sector headwind — defer buy'.
    """
    if not macro_intel.get("enabled"):
        return None
    sectors = macro_intel.get("sector_trends", {})
    av_sector = YF_TO_AV_SECTOR.get(yf_sector, yf_sector)
    for av_name, data in sectors.items():
        if av_name == av_sector or av_sector in av_name:
            if data.get("trend") == "underperform":
                rt = data.get("real_time_pct", 0)
                return f"Sector {av_name} underperforming ({rt:+.2f}% real-time)."
            break
    return None
