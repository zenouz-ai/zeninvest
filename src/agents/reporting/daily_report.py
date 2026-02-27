"""Daily report generation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

from src.data.database import get_session
from src.data.models import CostLog, Order, PortfolioSnapshot
from src.utils.cost_tracker import get_cost_summary
from src.utils.logger import get_logger

logger = get_logger("daily_report")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DAILY_DIR = _PROJECT_ROOT / "journals" / "daily"


def generate_daily_report(date: datetime | None = None) -> str:
    """Generate the daily report markdown.

    Returns:
        Path to the written report file.
    """
    if date is None:
        date = datetime.now(timezone.utc)

    _DAILY_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{date.strftime('%Y-%m-%d')}_daily.md"
    filepath = _DAILY_DIR / filename

    # Gather data
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    snapshot = _get_latest_snapshot(day_end)
    trades = _get_trades(day_start, day_end)
    cost = get_cost_summary(days=1)

    md = _build_daily_md(date, snapshot, trades, cost)
    filepath.write_text(md, encoding="utf-8")
    logger.info(f"Daily report written: {filepath}")
    return str(filepath)


def _get_latest_snapshot(before: datetime) -> dict[str, Any]:
    """Get the most recent portfolio snapshot."""
    session = get_session()
    try:
        snap = (
            session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.timestamp < before)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )
        if snap:
            return {
                "total_value": snap.total_value_gbp,
                "cash": snap.cash_gbp,
                "invested": snap.invested_gbp,
                "pnl_pct": snap.pnl_pct,
                "benchmark_pnl_pct": snap.benchmark_pnl_pct,
                "alpha_pct": snap.alpha_pct,
                "num_positions": snap.num_positions,
                "state": snap.state,
                "timestamp": snap.timestamp,
            }
        return {}
    finally:
        session.close()


def _get_trades(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Get trades executed in the time range."""
    session = get_session()
    try:
        orders = (
            session.query(Order)
            .filter(Order.timestamp >= start, Order.timestamp < end)
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
                "conviction": o.conviction,
                "journal_path": o.journal_path,
                "timestamp": o.timestamp,
            }
            for o in orders
        ]
    finally:
        session.close()


def _build_daily_md(
    date: datetime,
    snapshot: dict[str, Any],
    trades: list[dict[str, Any]],
    cost: dict[str, float],
) -> str:
    lines: list[str] = []

    lines.append(f"# Daily Report: {date.strftime('%Y-%m-%d')}")
    lines.append("")

    # Portfolio Summary
    lines.append("## Portfolio Summary")
    lines.append("")
    if snapshot:
        lines.append(f"- **Total Value:** \u00a3{snapshot.get('total_value', 0):,.2f}")
        lines.append(f"- **Cash:** \u00a3{snapshot.get('cash', 0):,.2f}")
        lines.append(f"- **Invested:** \u00a3{snapshot.get('invested', 0):,.2f}")
        lines.append(f"- **Positions:** {snapshot.get('num_positions', 0)}")
        lines.append(f"- **P&L:** {snapshot.get('pnl_pct', 0):+.2f}%")
        if snapshot.get("alpha_pct") is not None:
            lines.append(f"- **Alpha vs S&P 500:** {snapshot.get('alpha_pct', 0):+.2f}%")
        lines.append(f"- **System State:** {snapshot.get('state', 'N/A')}")
    else:
        lines.append("*No snapshot available*")
    lines.append("")

    # Today's Trades
    lines.append("## Today's Trades")
    lines.append("")
    if trades:
        lines.append("| Time | Action | Ticker | Qty | Price | Value | Strategy | Status |")
        lines.append("|------|--------|--------|-----|-------|-------|----------|--------|")
        for t in trades:
            ts = t["timestamp"].strftime("%H:%M") if t.get("timestamp") else "N/A"
            lines.append(
                f"| {ts} | {t['action']} | {t['ticker']} | "
                f"{abs(t.get('quantity', 0)):.2f} | {t.get('price', 0):.2f} | "
                f"\u00a3{t.get('value_gbp', 0):,.2f} | {t.get('strategy', 'N/A')} | "
                f"{t['status']} |"
            )
    else:
        lines.append("*No trades today*")
    lines.append("")

    # Cost Summary
    lines.append("## LLM Cost Summary")
    lines.append("")
    total_cost = cost.get("total", 0)
    lines.append(f"- **Total Today:** \u00a3{total_cost:.4f}")
    for provider in ["anthropic", "openai", "google"]:
        if provider in cost:
            lines.append(f"- **{provider.title()}:** \u00a3{cost[provider]:.4f}")
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*")
    lines.append("")

    return "\n".join(lines)
