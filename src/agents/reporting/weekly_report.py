"""Weekly report generation."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import func

from src.data.database import get_session
from src.data.models import (
    CostLog,
    ModerationLog,
    Order,
    PortfolioSnapshot,
    RiskDecision,
)
from src.utils.cost_tracker import get_cost_summary
from src.utils.logger import get_logger

logger = get_logger("weekly_report")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_WEEKLY_DIR = _PROJECT_ROOT / "journals" / "weekly"


def generate_weekly_report(end_date: datetime | None = None) -> str:
    """Generate the weekly report markdown.

    Returns:
        Path to the written report file.
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc)

    _WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    week_num = end_date.isocalendar()[1]
    filename = f"{end_date.strftime('%Y')}-W{week_num:02d}_weekly.md"
    filepath = _WEEKLY_DIR / filename

    start_date = end_date - timedelta(days=7)

    snapshots = _get_snapshots(start_date, end_date)
    trades = _get_week_trades(start_date, end_date)
    moderation_stats = _get_moderation_stats(start_date, end_date)
    risk_events = _get_risk_events(start_date, end_date)
    cost = _get_week_costs(start_date, end_date)

    md = _build_weekly_md(
        start_date, end_date, week_num,
        snapshots, trades, moderation_stats, risk_events, cost,
    )
    filepath.write_text(md, encoding="utf-8")
    logger.info(f"Weekly report written: {filepath}")
    return str(filepath)


def _get_snapshots(start: datetime, end: datetime) -> list[dict[str, Any]]:
    session = get_session()
    try:
        snaps = (
            session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.timestamp >= start, PortfolioSnapshot.timestamp <= end)
            .order_by(PortfolioSnapshot.timestamp)
            .all()
        )
        return [
            {
                "timestamp": s.timestamp,
                "total_value": s.total_value_gbp,
                "pnl_pct": s.pnl_pct,
                "benchmark_pnl_pct": s.benchmark_pnl_pct,
                "alpha_pct": s.alpha_pct,
                "num_positions": s.num_positions,
                "state": s.state,
            }
            for s in snaps
        ]
    finally:
        session.close()


def _get_week_trades(start: datetime, end: datetime) -> list[dict[str, Any]]:
    session = get_session()
    try:
        orders = (
            session.query(Order)
            .filter(Order.timestamp >= start, Order.timestamp <= end)
            .order_by(Order.timestamp)
            .all()
        )
        return [
            {
                "ticker": o.ticker,
                "action": o.action,
                "quantity": o.quantity,
                "price": o.price,
                "value_gbp": o.value_gbp,
                "status": o.status,
                "strategy": o.strategy,
                "timestamp": o.timestamp,
            }
            for o in orders
        ]
    finally:
        session.close()


def _get_moderation_stats(start: datetime, end: datetime) -> dict[str, Any]:
    session = get_session()
    try:
        logs = (
            session.query(ModerationLog)
            .filter(ModerationLog.timestamp >= start, ModerationLog.timestamp <= end)
            .all()
        )
        total = len(logs)
        agree = sum(1 for l in logs if l.verdict == "AGREE")
        disagree = sum(1 for l in logs if l.verdict == "DISAGREE")
        approved = sum(1 for l in logs if l.consensus == "APPROVED")
        blocked = sum(1 for l in logs if l.consensus == "BLOCKED")
        return {
            "total_reviews": total,
            "agree": agree,
            "disagree": disagree,
            "approved": approved,
            "blocked": blocked,
        }
    finally:
        session.close()


def _get_risk_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    session = get_session()
    try:
        decisions = (
            session.query(RiskDecision)
            .filter(
                RiskDecision.timestamp >= start,
                RiskDecision.timestamp <= end,
                RiskDecision.verdict != "APPROVE",
            )
            .order_by(RiskDecision.timestamp)
            .all()
        )
        return [
            {
                "ticker": d.ticker,
                "verdict": d.verdict,
                "reasoning": d.reasoning,
                "timestamp": d.timestamp,
            }
            for d in decisions
        ]
    finally:
        session.close()


def _get_week_costs(start: datetime, end: datetime) -> dict[str, float]:
    session = get_session()
    try:
        rows = (
            session.query(
                CostLog.provider,
                func.sum(CostLog.cost_gbp).label("total"),
            )
            .filter(CostLog.timestamp >= start, CostLog.timestamp <= end)
            .group_by(CostLog.provider)
            .all()
        )
        result: dict[str, float] = {}
        total = 0.0
        for row in rows:
            cost = float(row.total or 0)
            result[row.provider] = cost
            total += cost
        result["total"] = total
        return result
    finally:
        session.close()


def _build_weekly_md(
    start: datetime,
    end: datetime,
    week_num: int,
    snapshots: list[dict],
    trades: list[dict],
    moderation_stats: dict,
    risk_events: list[dict],
    cost: dict[str, float],
) -> str:
    lines: list[str] = []

    lines.append(f"# Weekly Report: W{week_num:02d} ({start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')})")
    lines.append("")

    # Performance
    lines.append("## Performance")
    lines.append("")
    if snapshots:
        latest = snapshots[-1]
        earliest = snapshots[0]
        weekly_return = latest["pnl_pct"] - earliest["pnl_pct"]
        lines.append(f"- **Portfolio Value:** \u00a3{latest['total_value']:,.2f}")
        lines.append(f"- **Weekly Return:** {weekly_return:+.2f}%")
        lines.append(f"- **Cumulative Return:** {latest['pnl_pct']:+.2f}%")
        if latest.get("benchmark_pnl_pct") is not None:
            lines.append(f"- **Benchmark (S&P 500):** {latest['benchmark_pnl_pct']:+.2f}%")
        if latest.get("alpha_pct") is not None:
            lines.append(f"- **Alpha:** {latest['alpha_pct']:+.2f}%")
        lines.append(f"- **Positions:** {latest['num_positions']}")

        # Sharpe ratio approximation (if enough data)
        if len(snapshots) >= 5:
            returns = []
            for i in range(1, len(snapshots)):
                r = (snapshots[i]["total_value"] / snapshots[i-1]["total_value"]) - 1
                returns.append(r)
            if returns:
                mean_r = np.mean(returns)
                std_r = np.std(returns)
                sharpe = (mean_r / std_r * np.sqrt(252)) if std_r > 0 else 0
                lines.append(f"- **Sharpe Ratio (approx):** {sharpe:.2f}")

        # Max drawdown
        peaks = []
        max_dd = 0.0
        running_peak = 0.0
        for s in snapshots:
            v = s["total_value"]
            if v > running_peak:
                running_peak = v
            dd = (running_peak - v) / running_peak * 100 if running_peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        lines.append(f"- **Max Drawdown:** {max_dd:.2f}%")
    else:
        lines.append("*No snapshot data available*")
    lines.append("")

    # Win Rate
    lines.append("## Trade Statistics")
    lines.append("")
    if trades:
        filled = [t for t in trades if t["status"] in ("filled", "dry_run")]
        lines.append(f"- **Total Trades:** {len(filled)}")
        buys = sum(1 for t in filled if t["action"] == "BUY")
        sells = sum(1 for t in filled if t["action"] in ("SELL", "REDUCE"))
        lines.append(f"- **Buys:** {buys}")
        lines.append(f"- **Sells:** {sells}")

        # Strategy attribution
        strats: dict[str, int] = {}
        for t in filled:
            s = t.get("strategy") or "unknown"
            strats[s] = strats.get(s, 0) + 1
        lines.append("- **Strategy Attribution:**")
        for s, count in sorted(strats.items(), key=lambda x: -x[1]):
            lines.append(f"  - {s}: {count} trades")
    else:
        lines.append("*No trades this week*")
    lines.append("")

    # Moderation Stats
    lines.append("## Moderation Panel")
    lines.append("")
    lines.append(f"- **Total Reviews:** {moderation_stats.get('total_reviews', 0)}")
    lines.append(f"- **Agree:** {moderation_stats.get('agree', 0)}")
    lines.append(f"- **Disagree:** {moderation_stats.get('disagree', 0)}")
    lines.append(f"- **Trades Approved:** {moderation_stats.get('approved', 0)}")
    lines.append(f"- **Trades Blocked:** {moderation_stats.get('blocked', 0)}")
    lines.append("")

    # Risk Events
    lines.append("## Risk Events")
    lines.append("")
    if risk_events:
        for event in risk_events:
            ts = event["timestamp"].strftime("%Y-%m-%d %H:%M") if event.get("timestamp") else "N/A"
            lines.append(f"- [{ts}] **{event['ticker']}** {event['verdict']}: {event.get('reasoning', 'N/A')}")
    else:
        lines.append("*No risk events this week*")
    lines.append("")

    # Cost Summary
    lines.append("## LLM Costs")
    lines.append("")
    total_cost = cost.get("total", 0)
    lines.append(f"- **Total This Week:** \u00a3{total_cost:.4f}")
    for provider in ["anthropic", "openai", "google"]:
        if provider in cost:
            lines.append(f"- **{provider.title()}:** \u00a3{cost[provider]:.4f}")
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*")
    lines.append("")

    return "\n".join(lines)
