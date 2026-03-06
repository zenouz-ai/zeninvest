"""Backtest metrics: Sharpe, Sortino, max drawdown, hit rate, turnover."""

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("backtesting.metrics")

_ANNUALIZE = 252 ** 0.5


def compute_metrics(
    equity_curve: list[tuple[Any, float]],
    trades: list[dict[str, Any]],
    benchmark_returns: list[float] | None = None,
) -> dict[str, Any]:
    """Compute performance metrics from equity curve and trade list.

    Args:
        equity_curve: List of (date, portfolio_value).
        trades: List of dicts with at least pnl_gbp or pnl_pct, side.
        benchmark_returns: Optional daily returns for benchmark (e.g. SPY).

    Returns:
        Dict with sharpe, sortino, max_drawdown_pct, cagr_pct, hit_rate_pct, turnover_pct, etc.
    """
    if len(equity_curve) < 2:
        return {
            "sharpe": None,
            "sortino": None,
            "max_drawdown_pct": None,
            "cagr_pct": None,
            "hit_rate_pct": None,
            "num_trades": 0,
            "turnover_pct": None,
        }

    values = [v for _, v in equity_curve]
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] and values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
        else:
            returns.append(0.0)

    mean_ret = sum(returns) / len(returns) if returns else 0.0
    variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns) if returns else 0.0
    std = variance ** 0.5
    downside_returns = [r for r in returns if r < 0]
    downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns) if downside_returns else 0.0
    downside_std = downside_var ** 0.5

    sharpe = (mean_ret / std * _ANNUALIZE) if std and std > 0 else None
    sortino = (mean_ret / downside_std * _ANNUALIZE) if downside_std and downside_std > 0 else None

    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

    n_days = len(values) - 1
    if n_days > 0 and values[0] and values[0] > 0 and values[-1] > 0:
        total_ret = values[-1] / values[0] - 1.0
        years = n_days / 252.0
        cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0.0
        cagr_pct = cagr * 100
    else:
        cagr_pct = None

    wins = sum(1 for t in trades if (t.get("pnl_gbp") or 0) > 0)
    num_trades = len(trades)
    hit_rate_pct = (wins / num_trades * 100) if num_trades else None

    # Turnover: total value traded / avg portfolio value (simplified)
    total_traded = sum(t.get("value", 0) or 0 for t in trades)
    avg_value = sum(values) / len(values) if values else 0
    turnover_pct = (total_traded / avg_value * 100) if avg_value and avg_value > 0 else None

    result: dict[str, Any] = {
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "sortino": round(sortino, 4) if sortino is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "cagr_pct": round(cagr_pct, 2) if cagr_pct is not None else None,
        "hit_rate_pct": round(hit_rate_pct, 2) if hit_rate_pct is not None else None,
        "num_trades": num_trades,
        "turnover_pct": round(turnover_pct, 2) if turnover_pct is not None else None,
    }
    if benchmark_returns and len(benchmark_returns) == len(returns):
        # Excess return (simplified)
        strat_ret = sum(returns) / len(returns) if returns else 0
        bench_ret = sum(benchmark_returns) / len(benchmark_returns)
        result["excess_return_vs_benchmark"] = round((strat_ret - bench_ret) * 100, 4)
    return result
