"""Performance metrics from portfolio snapshots and trade outcomes: Sharpe, Sortino, drawdown, win rates."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.data.models import Order, PerformanceMetric, PortfolioSnapshot, TradeOutcome
from src.utils.logger import get_logger

logger = get_logger("performance_tracker")

# Annualization factor for daily returns
_ANNUALIZE = 252 ** 0.5


def update_performance_metrics(as_of_date: datetime | None = None, session: Session | None = None) -> int:
    """Compute and persist performance metrics for the given date (UTC midnight).

    Uses portfolio_snapshots for return series and drawdown; uses trade_outcomes for win rates by strategy.
    Idempotent: replaces metric row for snapshot_date if present.

    Returns:
        Number of rows written (0 or 1).
    """
    from src.data.database import get_session

    own_session = session is None
    if session is None:
        session = get_session()
    try:
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            as_of_date = as_of_date.replace(hour=0, minute=0, second=0, microsecond=0)

        values = _compute_metrics(session, as_of_date)
        if values is None:
            return 0

        # Upsert: delete existing for this date then insert
        session.query(PerformanceMetric).filter(
            PerformanceMetric.snapshot_date >= as_of_date,
            PerformanceMetric.snapshot_date < as_of_date + timedelta(days=1),
        ).delete(synchronize_session=False)
        session.add(
            PerformanceMetric(
                snapshot_date=as_of_date,
                sharpe_30d=values.get("sharpe_30d"),
                sharpe_60d=values.get("sharpe_60d"),
                sharpe_90d=values.get("sharpe_90d"),
                sortino_30d=values.get("sortino_30d"),
                sortino_60d=values.get("sortino_60d"),
                sortino_90d=values.get("sortino_90d"),
                max_drawdown_pct=values.get("max_drawdown_pct"),
                calmar_ratio=values.get("calmar_ratio"),
                win_rate_momentum=values.get("win_rate_momentum"),
                win_rate_mean_reversion=values.get("win_rate_mean_reversion"),
                win_rate_factor=values.get("win_rate_factor"),
                alpha_vs_spy_pct=values.get("alpha_vs_spy_pct"),
                num_trades=values.get("num_trades"),
            )
        )
        session.commit()
        return 1
    except Exception as e:
        logger.error(f"Performance metrics update failed: {e}")
        session.rollback()
        return 0
    finally:
        if own_session:
            session.close()


def _compute_metrics(session: Session, as_of: datetime) -> dict[str, Any] | None:
    """Compute metric values from snapshots and trade_outcomes. Returns None if insufficient data."""
    # End of lookback for 90d
    start = as_of - timedelta(days=100)
    snapshots = (
        session.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.timestamp >= start,
            PortfolioSnapshot.timestamp <= as_of + timedelta(days=1),
        )
        .order_by(PortfolioSnapshot.timestamp.asc())
        .all()
    )

    if not snapshots:
        return None

    # Last snapshot per calendar day (UTC)
    by_day: dict[datetime, float] = {}
    for s in snapshots:
        day = s.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        by_day[day] = float(s.total_value_gbp)

    days = sorted(by_day.keys())
    if len(days) < 2:
        return _metrics_win_rates_only(session, as_of)

    # Daily returns
    returns: list[float] = []
    for i in range(1, len(days)):
        prev_val = by_day[days[i - 1]]
        curr_val = by_day[days[i]]
        if prev_val and prev_val > 0:
            returns.append((curr_val - prev_val) / prev_val)
        else:
            returns.append(0.0)

    result: dict[str, Any] = {}

    # Rolling Sharpe (annualized)
    if len(returns) >= 30:
        result["sharpe_30d"] = _annualized_ratio(returns[-30:], downside_only=False)
    else:
        result["sharpe_30d"] = None
    if len(returns) >= 60:
        result["sharpe_60d"] = _annualized_ratio(returns[-60:], downside_only=False)
    else:
        result["sharpe_60d"] = None
    if len(returns) >= 90:
        result["sharpe_90d"] = _annualized_ratio(returns[-90:], downside_only=False)
    else:
        result["sharpe_90d"] = None

    # Rolling Sortino (annualized, downside std only)
    if len(returns) >= 30:
        result["sortino_30d"] = _annualized_ratio(returns[-30:], downside_only=True)
    else:
        result["sortino_30d"] = None
    if len(returns) >= 60:
        result["sortino_60d"] = _annualized_ratio(returns[-60:], downside_only=True)
    else:
        result["sortino_60d"] = None
    if len(returns) >= 90:
        result["sortino_90d"] = _annualized_ratio(returns[-90:], downside_only=True)
    else:
        result["sortino_90d"] = None

    # Max drawdown (from peak) over full window
    values = list(by_day.values())
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    result["max_drawdown_pct"] = max_dd if max_dd > 0 else None

    # Calmar: CAGR / max_drawdown (simplified: use last 90d return annualized as proxy for CAGR if no 90d use 30d)
    if result["max_drawdown_pct"] and result["max_drawdown_pct"] > 0:
        if len(returns) >= 90:
            period_ret = (by_day[days[-1]] / by_day[days[-90]] - 1.0) if len(days) >= 90 else 0.0
            cagr = (1 + period_ret) ** (252 / 90) - 1 if period_ret > -1 else 0
        else:
            period_ret = (by_day[days[-1]] / by_day[days[-30]] - 1.0) if len(days) >= 30 else 0.0
            cagr = (1 + period_ret) ** (252 / 30) - 1 if period_ret > -1 else 0
        result["calmar_ratio"] = (cagr * 100 / result["max_drawdown_pct"]) if result["max_drawdown_pct"] else None
    else:
        result["calmar_ratio"] = None

    # Win rates by strategy from trade_outcomes
    wr = _win_rates_by_strategy(session, as_of)
    result["win_rate_momentum"] = wr.get("momentum")
    result["win_rate_mean_reversion"] = wr.get("mean_reversion")
    result["win_rate_factor"] = wr.get("factor")
    result["alpha_vs_spy_pct"] = _latest_alpha(session, as_of)
    result["num_trades"] = _count_trades(session, as_of)

    return result


def _metrics_win_rates_only(session: Session, as_of: datetime) -> dict[str, Any] | None:
    """When we have no snapshot series, still compute win rates and num_trades if possible."""
    wr = _win_rates_by_strategy(session, as_of)
    n = _count_trades(session, as_of)
    if n is None and not any(wr.values()):
        return None
    return {
        "sharpe_30d": None,
        "sharpe_60d": None,
        "sharpe_90d": None,
        "sortino_30d": None,
        "sortino_60d": None,
        "sortino_90d": None,
        "max_drawdown_pct": None,
        "calmar_ratio": None,
        "win_rate_momentum": wr.get("momentum"),
        "win_rate_mean_reversion": wr.get("mean_reversion"),
        "win_rate_factor": wr.get("factor"),
        "alpha_vs_spy_pct": _latest_alpha(session, as_of),
        "num_trades": n,
    }


def _annualized_ratio(returns: list[float], *, downside_only: bool = False) -> float | None:
    if not returns:
        return None
    mean_ret = sum(returns) / len(returns)
    if downside_only:
        neg = [r for r in returns if r < 0]
        std = (sum(r * r for r in neg) / len(neg)) ** 0.5 if neg else 0.0
    else:
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5
    if std is None or std <= 0:
        return None
    return mean_ret / std * _ANNUALIZE


def _win_rates_by_strategy(session: Session, as_of: datetime) -> dict[str, float | None]:
    """Win rate (fraction of trades with pnl_gbp > 0) per strategy."""
    cutoff = as_of - timedelta(days=365)
    rows = (
        session.query(TradeOutcome.strategy, TradeOutcome.pnl_gbp)
        .filter(TradeOutcome.sell_timestamp >= cutoff, TradeOutcome.sell_timestamp <= as_of + timedelta(days=1))
        .all()
    )
    by_strategy: dict[str, list[float]] = {}
    for strategy, pnl in rows:
        key = (strategy or "unknown").lower()
        if "momentum" in key:
            key = "momentum"
        elif "mean_rev" in key or "mean_reversion" in key:
            key = "mean_reversion"
        elif "factor" in key:
            key = "factor"
        else:
            key = "other"
        by_strategy.setdefault(key, []).append(float(pnl or 0))
    result: dict[str, float | None] = {}
    for name in ["momentum", "mean_reversion", "factor"]:
        arr = by_strategy.get(name, [])
        if arr:
            wins = sum(1 for p in arr if p > 0)
            result[name] = wins / len(arr) * 100
        else:
            result[name] = None
    return result


def _latest_alpha(session: Session, as_of: datetime) -> float | None:
    """Latest alpha_pct from a portfolio snapshot on or before as_of."""
    snap = (
        session.query(PortfolioSnapshot.alpha_pct)
        .filter(PortfolioSnapshot.timestamp <= as_of + timedelta(days=1))
        .order_by(PortfolioSnapshot.timestamp.desc())
        .first()
    )
    return float(snap[0]) if snap and snap[0] is not None else None


def _count_trades(session: Session, as_of: datetime) -> int | None:
    """Count of filled/dry_run orders (any action) on or before as_of."""
    return (
        session.query(Order)
        .filter(
            Order.timestamp <= as_of + timedelta(days=1),
            Order.status.in_(["filled", "dry_run"]),
        )
        .count()
    )
