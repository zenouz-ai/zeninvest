"""Trade journal — generates detailed markdown entries for every trade."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("journal")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_JOURNALS_DIR = _PROJECT_ROOT / "journals"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def generate_trade_journal(
    action: str,
    ticker: str,
    shares: float,
    price: float,
    value_gbp: float,
    weight_pct: float,
    conviction: int,
    strategy: str,
    reasoning: str,
    growth_potential: str,
    risk_level: str,
    catalysts: list[str],
    risks: list[str],
    exit_conditions: str,
    upside_target_pct: float,
    stop_loss_pct: float,
    expected_holding_period: str,
    market_regime: str,
    vix: float | None,
    sp500_trend: str,
    news_sentiment_overall: str,
    finnhub_data: dict[str, Any],
    alpha_vantage_data: dict[str, Any],
    moderation_results: dict[str, Any],
    risk_verdict: dict[str, Any],
    indicators: dict[str, Any],
    fundamentals: dict[str, Any],
    portfolio_state: dict[str, Any],
) -> str:
    """Generate a complete trade journal entry as markdown.

    Returns:
        Path to the written journal file.
    """
    _ensure_dir(_JOURNALS_DIR)
    now = datetime.utcnow()
    filename = f"{now.strftime('%Y-%m-%d_%H-%M')}_{ticker}_{action}.md"
    filepath = _JOURNALS_DIR / filename

    md = _build_markdown(
        action=action,
        ticker=ticker,
        shares=shares,
        price=price,
        value_gbp=value_gbp,
        weight_pct=weight_pct,
        conviction=conviction,
        strategy=strategy,
        reasoning=reasoning,
        growth_potential=growth_potential,
        risk_level=risk_level,
        catalysts=catalysts,
        risks=risks,
        exit_conditions=exit_conditions,
        upside_target_pct=upside_target_pct,
        stop_loss_pct=stop_loss_pct,
        expected_holding_period=expected_holding_period,
        market_regime=market_regime,
        vix=vix,
        sp500_trend=sp500_trend,
        news_sentiment_overall=news_sentiment_overall,
        finnhub_data=finnhub_data,
        alpha_vantage_data=alpha_vantage_data,
        moderation_results=moderation_results,
        risk_verdict=risk_verdict,
        indicators=indicators,
        fundamentals=fundamentals,
        portfolio_state=portfolio_state,
        timestamp=now,
    )

    filepath.write_text(md, encoding="utf-8")
    logger.info(f"Trade journal written: {filepath}")
    return str(filepath)


def _build_markdown(
    action: str,
    ticker: str,
    shares: float,
    price: float,
    value_gbp: float,
    weight_pct: float,
    conviction: int,
    strategy: str,
    reasoning: str,
    growth_potential: str,
    risk_level: str,
    catalysts: list[str],
    risks: list[str],
    exit_conditions: str,
    upside_target_pct: float,
    stop_loss_pct: float,
    expected_holding_period: str,
    market_regime: str,
    vix: float | None,
    sp500_trend: str,
    news_sentiment_overall: str,
    finnhub_data: dict[str, Any],
    alpha_vantage_data: dict[str, Any],
    moderation_results: dict[str, Any],
    risk_verdict: dict[str, Any],
    indicators: dict[str, Any],
    fundamentals: dict[str, Any],
    portfolio_state: dict[str, Any],
    timestamp: datetime,
) -> str:
    """Build the full markdown content for a trade journal entry."""
    lines: list[str] = []

    # Header
    lines.append(f"# Trade Journal: {action} {ticker}")
    lines.append(f"**Date:** {timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Decision Summary
    lines.append("## Decision Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Action | {action} |")
    lines.append(f"| Ticker | {ticker} |")
    lines.append(f"| Shares | {shares:.2f} |")
    lines.append(f"| Price | {_fmt_price(price)} |")
    lines.append(f"| Value | {_fmt_gbp(value_gbp)} |")
    lines.append(f"| Portfolio Weight | {weight_pct:.1f}% |")
    lines.append(f"| Conviction | {conviction}/100 |")
    lines.append(f"| Primary Strategy | {strategy} |")
    lines.append("")

    # Market Context
    lines.append("## Market Context")
    lines.append("")
    lines.append(f"- **Market Regime:** {market_regime}")
    lines.append(f"- **VIX:** {vix:.1f}" if vix else "- **VIX:** N/A")
    lines.append(f"- **S&P 500 Trend:** {sp500_trend}")
    lines.append(f"- **Overall News Sentiment:** {news_sentiment_overall}")
    lines.append("")

    # Strategy Rationale
    lines.append("## Strategy Rationale")
    lines.append("")
    lines.append(f"**Primary Strategy:** {strategy}")
    lines.append("")
    lines.append(reasoning)
    lines.append("")

    # Growth Potential
    lines.append("## Growth Potential")
    lines.append("")
    lines.append(f"- **Rating:** {growth_potential}")
    lines.append(f"- **Upside Target:** {upside_target_pct:+.1f}%")
    lines.append(f"- **Expected Holding Period:** {expected_holding_period}")
    lines.append(f"- **Catalysts:**")
    for c in catalysts:
        lines.append(f"  - {c}")
    lines.append("")

    # Risk Assessment
    lines.append("## Risk Assessment")
    lines.append("")
    lines.append(f"- **Risk Level:** {risk_level}")
    lines.append(f"- **Stop-Loss:** {stop_loss_pct:.1f}%")
    lines.append(f"- **Max Loss (value):** {_fmt_gbp(abs(value_gbp * stop_loss_pct / 100))}")
    lines.append(f"- **Key Risks:**")
    for r in risks:
        lines.append(f"  - {r}")
    lines.append("")

    # Exit Conditions
    lines.append("## Exit Conditions")
    lines.append("")
    lines.append(exit_conditions)
    lines.append("")

    # News & Sentiment Snapshot
    lines.append("## News & Sentiment Snapshot")
    lines.append("")
    _add_finnhub_section(lines, finnhub_data)
    _add_alpha_vantage_section(lines, alpha_vantage_data)
    lines.append("")

    # Moderation Panel Review
    lines.append("## Moderation Panel Review")
    lines.append("")
    _add_moderation_section(lines, moderation_results)
    lines.append("")

    # Risk Agent Decision
    lines.append("## Risk Agent Decision")
    lines.append("")
    lines.append(f"- **Verdict:** {risk_verdict.get('verdict', 'N/A')}")
    lines.append(f"- **Rules Checked:** {', '.join(risk_verdict.get('rules_checked', []))}")
    triggered = risk_verdict.get('triggered_rules', [])
    if triggered:
        lines.append(f"- **Triggered Rules:** {', '.join(triggered)}")
    lines.append(f"- **Reasoning:** {risk_verdict.get('reasoning', 'N/A')}")
    lines.append("")

    # Technical Snapshot
    lines.append("## Technical Snapshot")
    lines.append("")
    lines.append("| Indicator | Value |")
    lines.append("|-----------|-------|")
    lines.append(f"| RSI(14) | {_fmt_val(indicators.get('rsi_14'))} |")
    lines.append(f"| MACD Line | {_fmt_val(indicators.get('macd_line'))} |")
    lines.append(f"| MACD Signal | {_fmt_val(indicators.get('macd_signal'))} |")
    lines.append(f"| MACD Histogram | {_fmt_val(indicators.get('macd_histogram'))} |")
    lines.append(f"| 20-day MA | {_fmt_val(indicators.get('ma_20'))} |")
    lines.append(f"| 50-day MA | {_fmt_val(indicators.get('ma_50'))} |")
    lines.append(f"| 200-day MA | {_fmt_val(indicators.get('ma_200'))} |")
    lines.append(f"| BB Upper | {_fmt_val(indicators.get('bb_upper'))} |")
    lines.append(f"| BB Lower | {_fmt_val(indicators.get('bb_lower'))} |")
    lines.append(f"| BB Position | {_fmt_val(indicators.get('bb_pct'))} |")
    lines.append(f"| ATR(14) | {_fmt_val(indicators.get('atr_14'))} |")
    lines.append("")

    # Fundamental Snapshot
    lines.append("## Fundamental Snapshot")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| P/E (trailing) | {_fmt_val(fundamentals.get('trailing_pe'))} |")
    lines.append(f"| P/E (forward) | {_fmt_val(fundamentals.get('forward_pe'))} |")
    lines.append(f"| P/B | {_fmt_val(fundamentals.get('pb_ratio'))} |")
    lines.append(f"| ROE | {_fmt_pct(fundamentals.get('roe'))} |")
    lines.append(f"| Revenue Growth YoY | {_fmt_pct(fundamentals.get('revenue_growth_yoy'))} |")
    lines.append(f"| Earnings Growth | {_fmt_pct(fundamentals.get('earnings_growth'))} |")
    lines.append(f"| Profit Margin | {_fmt_pct(fundamentals.get('profit_margin'))} |")
    lines.append(f"| Debt/Equity | {_fmt_val(fundamentals.get('debt_equity'))} |")
    lines.append(f"| Sector | {fundamentals.get('sector', 'N/A')} |")
    lines.append("")

    # Post-Trade Portfolio State
    lines.append("## Post-Trade Portfolio State")
    lines.append("")
    lines.append(f"- **Total Value:** {_fmt_gbp(portfolio_state.get('total_value', 0))}")
    lines.append(f"- **Cash:** {_fmt_gbp(portfolio_state.get('cash', 0))}")
    lines.append(f"- **Invested:** {_fmt_gbp(portfolio_state.get('invested', 0))}")
    lines.append(f"- **Positions:** {portfolio_state.get('num_positions', 0)}")
    lines.append(f"- **Total Return:** {portfolio_state.get('total_return_pct', 0):+.2f}%")
    lines.append(f"- **Alpha vs S&P 500:** {portfolio_state.get('alpha_pct', 0):+.2f}%")
    lines.append("")

    positions = portfolio_state.get("positions", [])
    if positions:
        lines.append("### Current Positions")
        lines.append("")
        lines.append("| Ticker | Weight | P&L |")
        lines.append("|--------|--------|-----|")
        for pos in positions:
            lines.append(f"| {pos.get('ticker', 'N/A')} | {pos.get('weight_pct', 0):.1f}% | {pos.get('pnl_pct', 0):+.1f}% |")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by Investment Agent at {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}*")
    lines.append("")

    return "\n".join(lines)


def _add_finnhub_section(lines: list[str], data: dict[str, Any]) -> None:
    """Add Finnhub analyst data section (recommendations + insider sentiment)."""
    lines.append("### Finnhub Analyst Data")
    analyst = data.get("analyst_recommendations", {})
    insider = data.get("insider_sentiment", {})

    lines.append(f"- **Analyst Consensus:** {analyst.get('consensus', 'N/A')}")
    lines.append(f"- **Total Analysts:** {analyst.get('total_analysts', 'N/A')}")
    lines.append(f"- **Strong Buy/Buy/Hold/Sell/Strong Sell:** "
                 f"{analyst.get('strong_buy', 0)}/{analyst.get('buy', 0)}/"
                 f"{analyst.get('hold', 0)}/{analyst.get('sell', 0)}/"
                 f"{analyst.get('strong_sell', 0)}")
    lines.append(f"- **Insider MSPR:** {_fmt_val(insider.get('mspr'))}")


def _add_alpha_vantage_section(lines: list[str], data: dict[str, Any]) -> None:
    """Add Alpha Vantage sentiment data section."""
    lines.append("### Alpha Vantage")
    lines.append(f"- **Average Sentiment:** {_fmt_val(data.get('average_sentiment'))}")
    lines.append(f"- **Bullish Articles:** {data.get('bullish_articles', 'N/A')}")
    lines.append(f"- **Bearish Articles:** {data.get('bearish_articles', 'N/A')}")
    lines.append(f"- **Total Articles:** {data.get('total_articles', 'N/A')}")


def _add_moderation_section(lines: list[str], results: dict[str, Any]) -> None:
    """Add moderation panel results section."""
    lines.append(f"**Consensus:** {results.get('consensus', 'N/A')}")
    lines.append(f"**Moderators Available:** {results.get('moderators_available', 0)}")
    lines.append("")

    # Strategy (always AGREE)
    lines.append(f"- **Strategy Agent:** {results.get('strategy_verdict', 'AGREE')} — Primary proposer")

    # GPT-4o
    gpt = results.get("gpt4o_verdict")
    if gpt:
        lines.append(f"- **GPT-4o:** {gpt.get('verdict', 'N/A')} — {gpt.get('reasoning', 'N/A')}")
    else:
        lines.append("- **GPT-4o:** Not available")

    # Gemini
    gemini = results.get("gemini_verdict")
    if gemini:
        assessment = gemini.get("assessment") or gemini.get("reasoning", "N/A")
        lines.append(f"- **Gemini:** {gemini.get('verdict', 'N/A')} — {assessment}")
        g_score = gemini.get("growth_score")
        r_score = gemini.get("risk_score")
        c_score = gemini.get("confidence_score")
        if g_score is not None:
            lines.append(f"  - Growth: {g_score}/10, Risk: {r_score}/10, Confidence: {c_score}/10")
    else:
        lines.append("- **Gemini:** Not available")


def _fmt_gbp(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"\u00a3{val:,.2f}"


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:,.2f}"


def _fmt_val(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1%}"
