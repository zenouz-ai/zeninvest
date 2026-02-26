"""Shared context formatting for moderator prompts.

Both GPT-4o and Gemini moderators need the same structured data. This module
formats the raw market_context dict into a readable, token-efficient string
that moderators can reason over.
"""

import json
from typing import Any


def format_market_context(market_context: dict[str, Any]) -> str:
    """Format market context dict into readable text for moderator prompts.

    Sections:
    - Technical Indicators (RSI, MACD, Bollinger, MAs)
    - Fundamentals (P/E, ROE, margins, debt, earnings)
    - Market Conditions (VIX, regime, S&P trend)
    - Sub-Strategy Signals (momentum, mean reversion, factor scores)
    - Analyst & Insider Data (Finnhub recommendations, MSPR)
    - News Sentiment (Alpha Vantage headlines with scores)

    Args:
        market_context: Dict with keys: indicators, fundamentals, macro,
                       sub_strategies, analyst_data, news_sentiment.

    Returns:
        Formatted multi-line string for inclusion in moderator prompts.
    """
    sections: list[str] = []

    # --- Technical Indicators ---
    ind = market_context.get("indicators", {})
    if ind and "error" not in ind:
        lines = ["## Technical Indicators"]
        if "current_price" in ind:
            lines.append(f"- Price: ${ind['current_price']:.2f}")
        if "rsi_14" in ind:
            rsi = ind["rsi_14"]
            label = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral"
            lines.append(f"- RSI(14): {rsi:.1f} ({label})")
        if "macd_histogram" in ind:
            hist = ind["macd_histogram"]
            lines.append(f"- MACD Histogram: {hist:.4f} ({'positive' if hist > 0 else 'negative'})")
        if ind.get("macd_bullish_crossover"):
            lines.append("- MACD: Bullish crossover (buy signal)")
        if ind.get("macd_bearish_crossover"):
            lines.append("- MACD: Bearish crossover (sell signal)")
        if "above_50ma" in ind:
            lines.append(f"- Above 50-day MA: {'Yes' if ind['above_50ma'] else 'No'}")
        if "below_lower_bb" in ind:
            lines.append(f"- Below Lower Bollinger Band: {'Yes (oversold)' if ind['below_lower_bb'] else 'No'}")
        if "ma_20" in ind:
            lines.append(f"- 20-day MA: ${ind['ma_20']:.2f}")
        sections.append("\n".join(lines))

    # --- Fundamentals ---
    fund = market_context.get("fundamentals", {})
    if fund:
        lines = ["## Fundamentals"]
        _add_metric(lines, fund, "trailing_pe", "P/E", fmt=".1f")
        _add_metric(lines, fund, "pb_ratio", "P/B", fmt=".1f")
        _add_metric(lines, fund, "roe", "ROE", fmt=".1%")
        _add_metric(lines, fund, "profit_margin", "Profit Margin", fmt=".1%")
        _add_metric(lines, fund, "debt_equity", "Debt/Equity", fmt=".2f")
        _add_metric(lines, fund, "earnings_growth", "Earnings Growth", fmt=".1%")
        _add_metric(lines, fund, "earnings_momentum_qoq", "Earnings Momentum QoQ", fmt=".1%")
        if "sector" in fund:
            lines.append(f"- Sector: {fund['sector']}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # --- Market Conditions ---
    macro = market_context.get("macro", {})
    if macro:
        lines = ["## Market Conditions"]
        regime = macro.get("market_regime", "N/A")
        lines.append(f"- Market Regime: {regime}")
        vix = macro.get("vix")
        if vix is not None:
            vix_label = (
                "low" if vix < 15
                else "normal" if vix <= 20
                else "elevated" if vix <= 30
                else "high" if vix <= 35
                else "extreme"
            )
            lines.append(f"- VIX: {vix:.1f} ({vix_label})")
        sp_above = macro.get("sp500_above_200ma")
        if sp_above is not None:
            lines.append(f"- S&P 500 Above 200-day MA: {'Yes' if sp_above else 'No'}")
        sections.append("\n".join(lines))

    # --- Sub-Strategy Signals ---
    subs = market_context.get("sub_strategies", {})
    if subs:
        lines = ["## Sub-Strategy Signals"]
        mom = subs.get("momentum")
        if mom:
            lines.append(
                f"- Momentum: {mom['action']} (score: {mom['score']:.0f}) "
                f"— {mom['reasoning']}"
            )
        mr = subs.get("mean_reversion")
        if mr:
            lines.append(
                f"- Mean Reversion: {mr['action']} (score: {mr['score']:.0f}) "
                f"— {mr['reasoning']}"
            )
        fac = subs.get("factor")
        if fac:
            lines.append(
                f"- Factor: composite={fac['composite_score']:.0f} "
                f"(V={fac['value_score']:.0f} Q={fac['quality_score']:.0f} "
                f"M={fac['momentum_score']:.0f}) — {fac['reasoning']}"
            )
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # --- Analyst & Insider Data ---
    analyst = market_context.get("analyst_data", {})
    if analyst:
        lines = ["## Analyst & Insider Data"]
        # Format recommendation data compactly
        recs = analyst.get("recommendation", analyst.get("recommendations", {}))
        if recs:
            buy = recs.get("buy", 0)
            hold = recs.get("hold", 0)
            sell = recs.get("sell", 0)
            consensus = recs.get("consensus", "N/A")
            lines.append(f"- Analyst Consensus: {consensus} (Buy: {buy}, Hold: {hold}, Sell: {sell})")
        insider = analyst.get("insider", {})
        if insider:
            mspr = insider.get("mspr")
            if mspr is not None:
                mspr_label = "insiders buying" if mspr > 0 else "insiders selling" if mspr < 0 else "neutral"
                lines.append(f"- Insider Sentiment (MSPR): {mspr:.2f} ({mspr_label})")
        # If analyst data doesn't have sub-keys, dump it compactly
        if len(lines) == 1 and analyst:
            lines.append(json.dumps(analyst, indent=2, default=str)[:600])
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # --- News Sentiment ---
    news = market_context.get("news_sentiment", "")
    if news and news != "News sentiment data unavailable.":
        sections.append(f"## News Sentiment\n{news[:1500]}")

    return "\n\n".join(sections)


def _add_metric(
    lines: list[str],
    data: dict[str, Any],
    key: str,
    label: str,
    fmt: str = "",
) -> None:
    """Add a formatted metric line if the value exists and is not None."""
    val = data.get(key)
    if val is not None:
        if fmt:
            lines.append(f"- {label}: {val:{fmt}}")
        else:
            lines.append(f"- {label}: {val}")
