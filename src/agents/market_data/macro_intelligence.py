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

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
from src.agents.market_data.finnhub_client import FinnhubClient
from src.data.database import get_session
from src.data.models import MacroHeadline, MacroSignalLog, MacroState
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

        scored.sort(key=lambda x: (-x[0], -(x[1].get("datetime") or 0)))
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


# ---------------------------------------------------------------------------
# Headline archival for World News dashboard tab
# ---------------------------------------------------------------------------

_HEADLINE_CATEGORIES: list[tuple[str, list[str]]] = [
    ("fed", ["fed", "fomc", "federal reserve"]),
    ("rates", ["rate", "treasury", "bond", "yield"]),
    ("trade", ["tariff", "china", "trade war", "trade deal"]),
    ("earnings", ["earnings", "revenue", "profit", "quarterly"]),
    ("inflation", ["inflation", "cpi", "ppi", "consumer price"]),
    ("jobs", ["jobs", "employment", "unemployment", "nonfarm", "labour", "labor"]),
    ("gdp", ["gdp", "growth", "recession"]),
    ("market", ["s&p", "nasdaq", "dow", "rally", "selloff", "correction"]),
]


def categorize_headline(headline_text: str) -> str:
    """Assign a category to a headline based on keyword matching.

    Returns the first matching category, or 'general' as fallback.
    """
    text = headline_text.lower()
    for category, keywords in _HEADLINE_CATEGORIES:
        if any(kw in text for kw in keywords):
            return category
    return "general"


def persist_headlines(
    headlines: list[dict[str, Any]],
    *,
    cycle_id: str | None = None,
) -> int:
    """Archive headlines to the macro_headlines table for dashboard display.

    Returns number of new headlines inserted (duplicates are skipped).
    """
    if not headlines:
        return 0

    session = get_session()
    inserted = 0
    try:
        for h in headlines:
            headline_text = h.get("headline") or h.get("title") or ""
            if not headline_text:
                continue

            raw_dt = h.get("datetime")
            if raw_dt is None:
                published_at = datetime.now(timezone.utc)
            elif isinstance(raw_dt, (int, float)):
                published_at = datetime.fromtimestamp(raw_dt, tz=timezone.utc)
            elif isinstance(raw_dt, datetime):
                published_at = raw_dt
            else:
                published_at = datetime.now(timezone.utc)

            # Check for existing duplicate
            existing = (
                session.query(MacroHeadline.id)
                .filter(
                    MacroHeadline.headline == headline_text,
                    MacroHeadline.published_at == published_at,
                )
                .first()
            )
            if existing:
                continue

            row = MacroHeadline(
                headline=headline_text,
                source=h.get("source", "unknown"),
                published_at=published_at,
                url=h.get("url"),
                category=categorize_headline(headline_text),
                cycle_id=cycle_id,
            )
            session.add(row)
            inserted += 1

        session.commit()
        if inserted:
            logger.debug("Persisted %d new macro headlines", inserted)
        return inserted
    except Exception as e:
        session.rollback()
        logger.warning("Failed to persist macro headlines: %s", e)
        return 0
    finally:
        session.close()


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


def _derive_proactive_regime(vix: float | None, sp_above_200ma: bool | None) -> str:
    """Map baseline macro indicators to a proactive regime label."""
    if vix is not None and vix >= 30:
        return "RISK_OFF"
    if sp_above_200ma is False:
        return "RISK_OFF"
    if vix is not None and vix <= 18 and sp_above_200ma is True:
        return "RISK_ON"
    return "NEUTRAL"


def _confidence_from_inputs(
    *,
    vix: float | None,
    sp_above_200ma: bool | None,
    sector_count: int,
    headline_count: int,
) -> float:
    """Simple deterministic confidence score for the v1 proactive macro state."""
    confidence = 0.35
    if vix is not None:
        confidence += 0.15
    if sp_above_200ma is not None:
        confidence += 0.15
    if sector_count > 0:
        confidence += 0.20
    if headline_count > 0:
        confidence += 0.15
    return round(min(confidence, 0.95), 2)


def build_proactive_macro_state(macro_data: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic v1 proactive macro state from existing macro inputs."""
    macro_intel = macro_data.get("macro_intelligence", {}) or {}
    sector_trends = macro_intel.get("sector_trends", {}) or {}
    headlines = macro_intel.get("headlines", []) or []
    vix = macro_data.get("vix")
    sp_above = macro_data.get("sp500_above_200ma")
    regime = _derive_proactive_regime(vix, sp_above)

    top_signals: list[dict[str, Any]] = []
    if vix is not None:
        top_signals.append(
            {
                "signal_type": "volatility",
                "signal_text": f"VIX at {float(vix):.2f}",
                "source": "market_data",
            }
        )
    if sp_above is not None:
        position = "above" if sp_above else "below"
        top_signals.append(
            {
                "signal_type": "trend",
                "signal_text": f"S&P 500 trading {position} 200-day moving average",
                "source": "market_data",
            }
        )

    sector_signals = [
        (name, payload)
        for name, payload in sector_trends.items()
        if payload.get("trend") in {"underperform", "outperform"}
    ]
    sector_signals.sort(
        key=lambda item: abs(float(item[1].get("real_time_pct", 0.0))),
        reverse=True,
    )
    for name, payload in sector_signals[:2]:
        top_signals.append(
            {
                "signal_type": "sector",
                "signal_text": (
                    f"{name} {payload.get('trend')} "
                    f"({float(payload.get('real_time_pct', 0.0)):+.2f}% real-time)"
                ),
                "source": "macro_intelligence",
            }
        )

    if headlines:
        top_signals.append(
            {
                "signal_type": "headline",
                "signal_text": headlines[0].get("headline", "Macro headline detected"),
                "source": headlines[0].get("source", "finnhub"),
            }
        )

    top_signals = top_signals[:3]
    confidence = _confidence_from_inputs(
        vix=vix,
        sp_above_200ma=sp_above,
        sector_count=len(sector_trends),
        headline_count=len(headlines),
    )

    return {
        "enabled": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "confidence_score": confidence,
        "top_signals": top_signals,
        "sector_summary": macro_intel.get("sector_summary", ""),
        "economic_highlights": macro_intel.get("economic_highlights", ""),
        "source": "scheduled_scan",
        "raw_payload": {
            "vix": vix,
            "sp500_above_200ma": sp_above,
            "market_regime": macro_data.get("market_regime"),
            "macro_intelligence": macro_intel,
        },
    }


def _default_macro_action_plan(macro_state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback action plan used when LLM reasoning is disabled/unavailable."""
    regime = str(macro_state.get("regime", "NEUTRAL"))
    confidence = float(macro_state.get("confidence_score", 0.0))

    if regime == "RISK_OFF":
        portfolio_bias = "defensive"
        sector_implications = [
            {
                "sector": "Information Technology",
                "bias": "headwind",
                "confidence": confidence,
                "rationale": "Higher volatility and weaker broad-market trend reduce appetite for higher-beta growth exposure.",
            },
            {
                "sector": "Utilities",
                "bias": "tailwind",
                "confidence": max(confidence - 0.05, 0.0),
                "rationale": "Defensive sectors tend to hold up better during risk-off conditions.",
            },
        ]
        risks = ["Macro volatility may pressure cyclical and high-duration equities."]
        opportunities = ["Favor resilience, tighter stops, and patience on new growth entries."]
    elif regime == "RISK_ON":
        portfolio_bias = "constructive"
        sector_implications = [
            {
                "sector": "Information Technology",
                "bias": "tailwind",
                "confidence": confidence,
                "rationale": "Lower volatility and a healthy broad-market trend support momentum and quality growth leadership.",
            },
            {
                "sector": "Industrials",
                "bias": "tailwind",
                "confidence": max(confidence - 0.05, 0.0),
                "rationale": "Risk-on environments can support cyclical participation and follow-through.",
            },
        ]
        risks = ["Crowded momentum leadership can reverse quickly if volatility re-accelerates."]
        opportunities = ["Selective additions to strong relative-strength names are more attractive."]
    else:
        portfolio_bias = "balanced"
        sector_implications = [
            {
                "sector": "Market",
                "bias": "mixed",
                "confidence": confidence,
                "rationale": "Signals are mixed, so quality and stock-specific catalysts should matter more than top-down macro direction.",
            }
        ]
        risks = ["Range-bound conditions can create false breakouts and lower signal reliability."]
        opportunities = ["Favor selective entries, balanced sizing, and evidence-backed sector confirmation."]

    top_signals = macro_state.get("top_signals", [])
    summary = (
        f"Macro regime is {regime} with confidence {confidence:.2f}. "
        f"Primary signals: {'; '.join(s.get('signal_text', '') for s in top_signals[:3]) or 'none'}."
    )
    return {
        "summary": summary,
        "portfolio_bias": portfolio_bias,
        "confidence_score": confidence,
        "sector_implications": sector_implications,
        "risks": risks,
        "opportunities": opportunities,
    }


def generate_macro_action_plan(macro_state: dict[str, Any]) -> dict[str, Any]:
    """Generate structured second-order macro implications.

    Uses Claude when enabled and available, but always falls back to a deterministic
    structured plan so proactive scans remain robust and auditable.
    """
    settings = get_settings()
    if not settings.macro_second_order_reasoning_enabled:
        return _default_macro_action_plan(macro_state)

    prompt = f"""You are generating a structured macro action plan for an autonomous equity trading system.

Return JSON only with keys:
- summary: string
- portfolio_bias: one of defensive|balanced|constructive
- confidence_score: float 0-1
- sector_implications: list of objects with sector, bias (tailwind|headwind|mixed), confidence, rationale
- risks: list[str]
- opportunities: list[str]

Current macro state:
{json.dumps(macro_state, indent=2, default=str)}
"""

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.strategy_model,
            max_tokens=1200,
            system="You produce concise, valid JSON for macro portfolio reasoning.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(
            block.text for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"
        ).strip()
        parsed = json.loads(raw_text)
        parsed.setdefault("confidence_score", float(macro_state.get("confidence_score", 0.0)))
        parsed.setdefault("sector_implications", [])
        parsed.setdefault("risks", [])
        parsed.setdefault("opportunities", [])
        return parsed
    except Exception as e:
        logger.warning("Macro action plan generation failed, using deterministic fallback: %s", e)
        fallback = _default_macro_action_plan(macro_state)
        fallback["summary"] = f"{fallback['summary']} (Fallback used: {type(e).__name__})"
        return fallback


def run_proactive_macro_scan(
    alpha_vantage: AlphaVantageClient,
    finnhub: FinnhubClient,
) -> dict[str, Any]:
    """Build and persist the latest proactive macro state and action plan."""
    from src.agents.market_data.data_fetcher import DataFetcher

    settings = get_settings()
    if not settings.macro_proactive_scan_enabled:
        return {"status": "disabled"}

    fetcher = DataFetcher(alpha_vantage=alpha_vantage, finnhub=finnhub)
    try:
        macro_data = fetcher.get_macro_data()
        macro_state = build_proactive_macro_state(macro_data)
        macro_state["action_plan"] = generate_macro_action_plan(macro_state)
        persisted = persist_macro_state(
            macro_state,
            signal_log_enabled=settings.macro_signal_log_enabled,
        )
        return {
            "status": "ok",
            "regime": macro_state["regime"],
            "confidence_score": macro_state["confidence_score"],
            "state_id": persisted["state_id"],
            "top_signals": macro_state["top_signals"],
            "action_plan": macro_state["action_plan"],
        }
    finally:
        fetcher.close()


def persist_macro_state(
    macro_state: dict[str, Any],
    *,
    signal_log_enabled: bool = True,
) -> dict[str, Any]:
    """Persist macro state snapshot and normalized signal logs."""
    session = get_session()
    try:
        created_at = datetime.now(timezone.utc)
        row = MacroState(
            timestamp=created_at,
            regime=str(macro_state.get("regime", "NEUTRAL")),
            confidence_score=float(macro_state.get("confidence_score", 0.0)),
            source=str(macro_state.get("source", "scheduled_scan")),
            top_signals_json=json.dumps(macro_state.get("top_signals", []), default=str),
            action_plan_json=json.dumps(macro_state.get("action_plan", {}), default=str),
            sector_summary=macro_state.get("sector_summary"),
            economic_highlights=macro_state.get("economic_highlights"),
            raw_payload_json=json.dumps(macro_state.get("raw_payload", {}), default=str),
        )
        session.add(row)
        session.flush()

        if signal_log_enabled:
            for signal in macro_state.get("top_signals", []):
                session.add(
                    MacroSignalLog(
                        timestamp=created_at,
                        state_id=row.id,
                        signal_type=str(signal.get("signal_type", "macro")),
                        signal_text=str(signal.get("signal_text", "")),
                        source=str(signal.get("source", macro_state.get("source", "scheduled_scan"))),
                        confidence_score=float(macro_state.get("confidence_score", 0.0)),
                        regime=str(macro_state.get("regime", "NEUTRAL")),
                    )
                )

        session.commit()
        return {
            "status": "ok",
            "state_id": row.id,
            "num_signals": len(macro_state.get("top_signals", [])) if signal_log_enabled else 0,
            "regime": row.regime,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_latest_macro_state() -> dict[str, Any] | None:
    """Return the latest persisted proactive macro state, if available."""
    session = get_session()
    try:
        latest = session.query(MacroState).order_by(MacroState.timestamp.desc()).first()
        if latest is None:
            return None
        return {
            "enabled": True,
            "timestamp": latest.timestamp.isoformat() if latest.timestamp else None,
            "regime": latest.regime,
            "confidence_score": latest.confidence_score,
            "source": latest.source,
            "top_signals": json.loads(latest.top_signals_json or "[]"),
            "action_plan": json.loads(latest.action_plan_json or "{}"),
            "sector_summary": latest.sector_summary or "",
            "economic_highlights": latest.economic_highlights or "",
            "raw_payload": json.loads(latest.raw_payload_json or "{}"),
        }
    finally:
        session.close()
