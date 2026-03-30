#!/usr/bin/env python3
"""Diagnostic script to audit performance metrics data quality.

This script validates that the backend data sources for performance metrics
(PortfolioSnapshot, TradeOutcome, Order, PerformanceMetric) are properly
populated and consistent.

Usage:
    poetry run python scripts/audit_performance_data.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.data.database import get_session
from src.data.models import Order, PerformanceMetric, PortfolioSnapshot, TradeOutcome

# Import Run from dashboard backend if available (optional for basic audit)
try:
    from dashboard.backend.app.database import Run
    DASHBOARD_RUN_AVAILABLE = True
except ImportError:
    DASHBOARD_RUN_AVAILABLE = False
    Run = None
from src.utils.logger import get_logger

logger = get_logger("audit_performance_data")


def _format_timestamp(ts: datetime | None) -> str:
    if ts is None:
        return "None"
    return ts.strftime("%Y-%m-%d %H:%M:%S UTC")


def audit_portfolio_snapshots(session) -> dict:
    """Audit PortfolioSnapshot table for data quality."""
    findings = {
        "severity": "INFO",
        "row_count": 0,
        "date_range": None,
        "has_nulls": False,
        "null_columns": [],
        "issues": [],
    }

    try:
        row_count = session.query(func.count(PortfolioSnapshot.id)).scalar() or 0
        findings["row_count"] = row_count

        if row_count == 0:
            findings["severity"] = "CRITICAL"
            findings["issues"].append("No portfolio snapshots found — metrics cannot be calculated")
            return findings

        # Get date range
        first_snap = (
            session.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.asc()).first()
        )
        last_snap = (
            session.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.desc()).first()
        )

        if first_snap and last_snap:
            findings["date_range"] = {
                "first": _format_timestamp(first_snap.timestamp),
                "last": _format_timestamp(last_snap.timestamp),
                "days": (last_snap.timestamp - first_snap.timestamp).days,
            }

        # Check for null values in critical columns
        null_counts = {
            "total_value_gbp": session.query(func.count(PortfolioSnapshot.id)).filter(
                PortfolioSnapshot.total_value_gbp.is_(None)
            ).scalar() or 0,
            "cash_gbp": session.query(func.count(PortfolioSnapshot.id)).filter(
                PortfolioSnapshot.cash_gbp.is_(None)
            ).scalar() or 0,
            "invested_gbp": session.query(func.count(PortfolioSnapshot.id)).filter(
                PortfolioSnapshot.invested_gbp.is_(None)
            ).scalar() or 0,
            "pnl_gbp": session.query(func.count(PortfolioSnapshot.id)).filter(
                PortfolioSnapshot.pnl_gbp.is_(None)
            ).scalar() or 0,
        }

        if any(null_counts.values()):
            findings["has_nulls"] = True
            findings["null_columns"] = {k: v for k, v in null_counts.items() if v > 0}
            findings["severity"] = "HIGH"
            findings["issues"].append(
                f"Found null values in critical columns: {findings['null_columns']}"
            )

        # Check if we have enough data for Sharpe calculation (need ≥30 days)
        if findings["date_range"] and findings["date_range"]["days"] < 30:
            findings["severity"] = "WARNING" if findings["severity"] == "INFO" else findings["severity"]
            findings["issues"].append(
                f"Insufficient data for Sharpe calculation: only {findings['date_range']['days']} days"
            )

        # Check for data gaps (if row_count is much less than days, snapshots are sparse)
        if findings["date_range"]:
            expected_min = max(3, findings["date_range"]["days"])  # At least 3 per day if intraday
            if row_count < expected_min:
                findings["issues"].append(
                    f"Sparse snapshots: {row_count} rows over {findings['date_range']['days']} days "
                    f"(expect ≥{expected_min})"
                )

    except Exception as e:
        findings["severity"] = "ERROR"
        findings["issues"].append(f"Exception: {e}")

    return findings


def audit_trade_outcomes(session) -> dict:
    """Audit TradeOutcome table for closed trades."""
    findings = {
        "severity": "INFO",
        "row_count": 0,
        "by_strategy": {},
        "avg_pnl_gbp": None,
        "issues": [],
    }

    try:
        row_count = session.query(func.count(TradeOutcome.id)).scalar() or 0
        findings["row_count"] = row_count

        if row_count == 0:
            findings["severity"] = "WARNING"
            findings["issues"].append("No closed trades yet (expected in early track record)")
            return findings

        # Breakdown by strategy
        by_strategy = (
            session.query(TradeOutcome.strategy, func.count(TradeOutcome.id), func.avg(TradeOutcome.pnl_gbp))
            .group_by(TradeOutcome.strategy)
            .all()
        )

        for strategy, count, avg_pnl in by_strategy:
            findings["by_strategy"][strategy or "unknown"] = {
                "count": count,
                "avg_pnl_gbp": float(avg_pnl) if avg_pnl else 0.0,
            }

        # Overall average P&L
        avg_pnl = session.query(func.avg(TradeOutcome.pnl_gbp)).scalar()
        findings["avg_pnl_gbp"] = float(avg_pnl) if avg_pnl else 0.0

    except Exception as e:
        findings["severity"] = "ERROR"
        findings["issues"].append(f"Exception: {e}")

    return findings


def audit_orders(session) -> dict:
    """Audit Order table for trade count."""
    findings = {
        "severity": "INFO",
        "filled_count": 0,
        "by_action": {},
        "by_status": {},
        "issues": [],
    }

    try:
        # Count filled orders (filled status)
        filled_count = (
            session.query(func.count(Order.id))
            .filter(Order.status.in_(["filled", "dry_run"]))
            .scalar() or 0
        )
        findings["filled_count"] = filled_count

        # Breakdown by action
        by_action = (
            session.query(Order.action, func.count(Order.id))
            .filter(Order.status.in_(["filled", "dry_run"]))
            .group_by(Order.action)
            .all()
        )
        findings["by_action"] = {action: count for action, count in by_action}

        # Full breakdown by status
        by_status = (
            session.query(Order.status, func.count(Order.id)).group_by(Order.status).all()
        )
        findings["by_status"] = {status: count for status, count in by_status}

    except Exception as e:
        findings["severity"] = "ERROR"
        findings["issues"].append(f"Exception: {e}")

    return findings


def audit_performance_metrics(session) -> dict:
    """Audit PerformanceMetric table for calculated metrics."""
    findings = {
        "severity": "INFO",
        "row_count": 0,
        "latest_metric": None,
        "date_range": None,
        "issues": [],
    }

    try:
        row_count = session.query(func.count(PerformanceMetric.id)).scalar() or 0
        findings["row_count"] = row_count

        if row_count == 0:
            findings["severity"] = "WARNING"
            findings["issues"].append("No performance metrics calculated yet")
            return findings

        # Get latest metric
        latest = (
            session.query(PerformanceMetric).order_by(PerformanceMetric.snapshot_date.desc()).first()
        )

        if latest:
            findings["latest_metric"] = {
                "date": _format_timestamp(latest.snapshot_date),
                "sharpe_30d": round(latest.sharpe_30d, 2) if latest.sharpe_30d else None,
                "sharpe_60d": round(latest.sharpe_60d, 2) if latest.sharpe_60d else None,
                "sortino_30d": round(latest.sortino_30d, 2) if latest.sortino_30d else None,
                "max_drawdown_pct": round(latest.max_drawdown_pct, 2) if latest.max_drawdown_pct else None,
                "win_rate_momentum": round(latest.win_rate_momentum, 1) if latest.win_rate_momentum else None,
                "win_rate_mean_reversion": round(latest.win_rate_mean_reversion, 1) if latest.win_rate_mean_reversion else None,
                "win_rate_factor": round(latest.win_rate_factor, 1) if latest.win_rate_factor else None,
                "num_trades": latest.num_trades,
            }

            # Check for missing values (should be populated if row exists)
            missing = []
            for key, value in findings["latest_metric"].items():
                if key != "date" and key != "num_trades" and value is None:
                    missing.append(key)
            if missing:
                findings["issues"].append(f"Missing values in latest metric: {missing}")
                findings["severity"] = "WARNING"

        first_metric = (
            session.query(PerformanceMetric).order_by(PerformanceMetric.snapshot_date.asc()).first()
        )
        if first_metric and latest:
            findings["date_range"] = {
                "first": _format_timestamp(first_metric.snapshot_date),
                "last": _format_timestamp(latest.snapshot_date),
            }

    except Exception as e:
        findings["severity"] = "ERROR"
        findings["issues"].append(f"Exception: {e}")

    return findings


def audit_run_count(session) -> dict:
    """Audit Run table to understand cycle frequency."""
    findings = {
        "severity": "INFO",
        "total_runs": 0,
        "by_type": {},
        "recent_completed": 0,
        "issues": [],
    }

    if not DASHBOARD_RUN_AVAILABLE or Run is None:
        findings["issues"].append("Run model not available (dashboard backend not configured)")
        return findings

    try:
        total = session.query(func.count(Run.id)).scalar() or 0
        findings["total_runs"] = total

        if total == 0:
            findings["severity"] = "WARNING"
            findings["issues"].append("No runs recorded yet")
            return findings

        # Count by run_type
        by_type = session.query(Run.run_type, func.count(Run.id)).group_by(Run.run_type).all()
        findings["by_type"] = {run_type: count for run_type, count in by_type}

        # Completed runs in last 24h
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        recent = (
            session.query(func.count(Run.id))
            .filter(Run.completed_at >= yesterday, Run.status == "completed")
            .scalar() or 0
        )
        findings["recent_completed"] = recent

    except Exception as e:
        findings["severity"] = "ERROR"
        findings["issues"].append(f"Exception: {e}")

    return findings


def generate_report() -> str:
    """Generate audit report."""
    session = get_session()
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        report = []
        report.append("# Performance Metrics Data Quality Audit")
        report.append(f"\n**Generated:** {timestamp}\n")

        # Portfolio Snapshots
        report.append("## PortfolioSnapshot Table")
        snap_audit = audit_portfolio_snapshots(session)
        report.append(f"- **Row Count:** {snap_audit['row_count']}")
        if snap_audit["date_range"]:
            dr = snap_audit["date_range"]
            report.append(f"- **Date Range:** {dr['first']} to {dr['last']} ({dr['days']} days)")
        if snap_audit["null_columns"]:
            report.append(f"- **Null Values:** {snap_audit['null_columns']}")
        for issue in snap_audit["issues"]:
            report.append(f"- ⚠️ {issue}")
        if not snap_audit["issues"]:
            report.append("- ✅ No data quality issues")

        # Trade Outcomes
        report.append("\n## TradeOutcome Table (Closed Trades)")
        outcome_audit = audit_trade_outcomes(session)
        report.append(f"- **Row Count:** {outcome_audit['row_count']}")
        report.append(f"- **Avg P&L:** £{outcome_audit['avg_pnl_gbp']:.2f}")
        if outcome_audit["by_strategy"]:
            report.append("- **By Strategy:**")
            for strat, data in outcome_audit["by_strategy"].items():
                report.append(
                    f"  - {strat}: {data['count']} trades, avg P&L £{data['avg_pnl_gbp']:.2f}"
                )
        for issue in outcome_audit["issues"]:
            report.append(f"- ℹ️ {issue}")

        # Orders
        report.append("\n## Order Table (Trade Count)")
        order_audit = audit_orders(session)
        report.append(f"- **Filled/DryRun Count:** {order_audit['filled_count']}")
        if order_audit["by_action"]:
            report.append("- **By Action:** " + ", ".join(
                f"{action}={count}" for action, count in order_audit["by_action"].items()
            ))
        if order_audit["by_status"]:
            report.append("- **By Status:** " + ", ".join(
                f"{status}={count}" for status, count in order_audit["by_status"].items()
            ))

        # Performance Metrics
        report.append("\n## PerformanceMetric Table (Calculated Metrics)")
        perf_audit = audit_performance_metrics(session)
        report.append(f"- **Row Count:** {perf_audit['row_count']}")
        if perf_audit["latest_metric"]:
            lm = perf_audit["latest_metric"]
            report.append(f"- **Latest Date:** {lm['date']}")
            report.append(f"  - Sharpe (30d): {lm['sharpe_30d']}")
            report.append(f"  - Sharpe (60d): {lm['sharpe_60d']}")
            report.append(f"  - Sortino (30d): {lm['sortino_30d']}")
            report.append(f"  - Max Drawdown: {lm['max_drawdown_pct']}%")
            report.append(f"  - Win Rates (momentum/mean-rev/factor): {lm['win_rate_momentum']}% / {lm['win_rate_mean_reversion']}% / {lm['win_rate_factor']}%")
            report.append(f"  - Num Trades: {lm['num_trades']}")
        for issue in perf_audit["issues"]:
            report.append(f"- ⚠️ {issue}")

        # Run Summary
        report.append("\n## Run Table (Cycle Frequency)")
        run_audit = audit_run_count(session)
        report.append(f"- **Total Runs:** {run_audit['total_runs']}")
        report.append(f"- **Recent Completed (last 24h):** {run_audit['recent_completed']}")
        if run_audit["by_type"]:
            report.append("- **By Type:** " + ", ".join(
                f"{run_type}={count}" for run_type, count in run_audit["by_type"].items()
            ))
        for issue in run_audit["issues"]:
            report.append(f"- ℹ️ {issue}")

        # Summary
        report.append("\n## Summary & Recommendations")
        all_findings = [snap_audit, outcome_audit, perf_audit]
        max_severity_order = {"ERROR": 0, "CRITICAL": 1, "HIGH": 2, "WARNING": 3, "INFO": 4}
        max_severity = max(
            (max_severity_order.get(f["severity"], 5) for f in all_findings),
            default=None,
        )
        severity_name = {0: "ERROR", 1: "CRITICAL", 2: "HIGH", 3: "WARNING", 4: "INFO"}.get(max_severity, "UNKNOWN")

        report.append(f"\n**Overall Severity:** {severity_name}")

        if snap_audit["row_count"] < 10:
            report.append("\n### Action: Insufficient PortfolioSnapshot Data")
            report.append(
                "- Verify cycles are completing and `save_portfolio_snapshot()` is called each time"
            )
            report.append("- Check `runs` table for failed/incomplete cycles")

        if perf_audit["row_count"] < 5:
            report.append("\n### Action: No Performance Metrics Yet")
            report.append(
                "- Run at least one live cycle to generate snapshots and metrics"
            )
            report.append("- Performance calculation requires ≥2 snapshots; Sharpe requires ≥30 days")

        if outcome_audit["row_count"] < 2:
            report.append("\n### Action: No Closed Trades Yet")
            report.append(
                "- TradeOutcome requires both BUY and SELL executions; still early in track record"
            )
            report.append("- This is expected for new systems")

        report.append("\n---\n")
        return "\n".join(report)

    finally:
        session.close()


if __name__ == "__main__":
    report = generate_report()
    print(report)

    # Save to file
    output_file = project_root / "data" / "runtime" / "audit_performance_data.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(report)
    print(f"\n✅ Audit report saved to: {output_file}")
