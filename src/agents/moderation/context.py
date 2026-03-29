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
        if ind.get("obv") is not None:
            lines.append(f"- OBV: {ind['obv']:.0f}")
        if ind.get("volume_sma_ratio_20") is not None:
            lines.append(f"- Volume vs 20-day avg: {ind['volume_sma_ratio_20']:.2f}x")
        if "obv_rising_5d" in ind:
            lines.append(f"- OBV Rising (5d): {'Yes' if ind['obv_rising_5d'] else 'No'}")
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

    earnings = market_context.get("earnings", {})
    overlap = market_context.get("portfolio_overlap", {})
    if earnings or overlap:
        lines = ["## Entry Quality Guards"]
        next_earnings = earnings.get("next_earnings_date")
        if next_earnings:
            days = earnings.get("trading_days_to_earnings")
            imminent = "Yes" if earnings.get("earnings_imminent") else "No"
            if days is not None:
                lines.append(f"- Next Earnings: {next_earnings} ({days} trading days, imminent: {imminent})")
            else:
                lines.append(f"- Next Earnings: {next_earnings} (imminent: {imminent})")
        recent_earnings = earnings.get("recent_earnings_date")
        if recent_earnings:
            surprise = earnings.get("recent_earnings_surprise_pct")
            surprise_text = f"{surprise:.2f}%" if surprise is not None else "unknown"
            lines.append(f"- Recent Earnings: {recent_earnings} (surprise: {surprise_text})")
        if earnings.get("post_earnings_drift_active"):
            drift_bias = earnings.get("post_earnings_drift_bias", "unknown")
            drift_change = earnings.get("post_earnings_price_change_pct")
            drift_change_text = f"{drift_change:.2f}%" if drift_change is not None else "unknown"
            lines.append(f"- Post-Earnings Drift: {drift_bias} ({drift_change_text})")
        avg_corr = overlap.get("avg_correlation")
        max_corr = overlap.get("max_correlation")
        if avg_corr is not None:
            max_corr_text = f", max {max_corr:.2f}" if max_corr is not None else ""
            high_flag = "Yes" if overlap.get("high_correlation_flag") else "No"
            lines.append(
                f"- Portfolio Overlap: avg {avg_corr:.2f}{max_corr_text} (high correlation: {high_flag})"
            )
        top_overlaps = overlap.get("top_overlaps") or []
        if top_overlaps:
            lines.append(
                "- Top Overlaps: "
                + ", ".join(
                    f"{item.get('ticker', 'UNKNOWN')} {float(item.get('correlation', 0.0)):.2f}"
                    for item in top_overlaps[:2]
                )
            )
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
        sector_headwind = macro.get("sector_headwind")
        if sector_headwind:
            lines.append(f"- Sector Headwind: {sector_headwind}")
        sector_summary = macro.get("sector_summary")
        if sector_summary:
            lines.append(f"- Sector Performance: {sector_summary[:400]}")
        economic_highlights = macro.get("economic_highlights")
        if economic_highlights:
            lines.append(f"- Economic Highlights: {economic_highlights[:500]}")
        proactive_regime = macro.get("proactive_regime")
        if proactive_regime:
            conf = macro.get("proactive_confidence")
            if conf is not None:
                lines.append(f"- Proactive Macro Regime: {proactive_regime} (confidence {float(conf):.2f})")
            else:
                lines.append(f"- Proactive Macro Regime: {proactive_regime}")
        proactive_signals = macro.get("proactive_top_signals") or []
        if proactive_signals:
            lines.append(
                "- Proactive Signals: "
                + " | ".join(
                    f"{sig.get('signal_type', 'macro')}: {sig.get('signal_text', '')}"
                    for sig in proactive_signals[:3]
                )[:500]
            )
        macro_action_plan = macro.get("macro_action_plan") or {}
        if macro_action_plan.get("summary"):
            lines.append(f"- Macro Action Plan: {macro_action_plan['summary'][:500]}")
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

    # --- Strategy Agent's Market Assessment ---
    assessment = market_context.get("strategy_assessment", "")
    if assessment:
        sections.append(
            f"## Strategy Agent's Market Assessment\n"
            f"(Challenge this thesis — do you agree with the reasoning?)\n{assessment[:500]}"
        )

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
