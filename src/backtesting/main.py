"""CLI entrypoint for backtest runs and result export."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import pandas as pd

from src.backtesting.engine import BacktestEngine
from src.backtesting.io import generate_synthetic_bars, load_bars, load_benchmark
from src.backtesting.promotion_report import write_promotion_report
from src.backtesting.walk_forward import aggregate_fold_metrics, make_splits, run_walk_forward
from src.utils.logger import get_logger

logger = get_logger("backtesting.main")


def _load_config(config_path: Path) -> dict:
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


@click.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None, help="Path to backtest config YAML")
@click.option("--seed", type=int, default=None, help="Random seed (overrides config)")
@click.option("--synthetic", is_flag=True, help="Use synthetic data for a quick run")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None, help="Results directory (default: backtests/results/<timestamp>)")
@click.option("--walk-forward", is_flag=True, help="Run walk-forward validation over multiple folds")
@click.option("--scenario", type=str, default=None, help="Scenario name: bull, bear, or sideways (uses backtests/scenarios/<name>.yaml)")
def main(
    config_path: Path | None,
    seed: int | None,
    synthetic: bool,
    output_dir: Path | None,
    walk_forward: bool,
    scenario: str | None,
) -> None:
    """Run backtest and write results.json, trades.csv, equity_curve.csv, run_metadata.json."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    config: dict = {}
    if scenario:
        scenario_path = base_dir / "backtests" / "scenarios" / f"{scenario}.yaml"
        if scenario_path.exists():
            config_path = scenario_path
    if config_path and config_path.exists():
        config = _load_config(config_path)
    if not config and (base_dir / "backtests" / "default.yaml").exists():
        config = _load_config(base_dir / "backtests" / "default.yaml")

    if seed is not None:
        config["seed"] = seed
    if "seed" not in config:
        config["seed"] = 42

    tickers = config.get("tickers", ["AAPL", "MSFT", "SPY"])
    start_str = config.get("start_date")
    end_str = config.get("end_date")
    if not start_str or not end_str:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=365 * 2)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
    start = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if "T" in end_str else datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if synthetic:
        bars = {}
        for t in tickers:
            bars[t] = generate_synthetic_bars(t, pd.Timestamp(start), pd.Timestamp(end), seed=config["seed"])
        benchmark = bars.get("SPY", pd.DataFrame())
        if not benchmark.empty:
            benchmark = benchmark.set_index("date")["close"]
        else:
            benchmark = None
    else:
        bars = load_bars(tickers, start, end)
        benchmark = load_benchmark("SPY", start, end)

    if not bars:
        click.echo("No bar data loaded. Use --synthetic for a quick test.")
        raise SystemExit(1)

    if output_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_dir = base_dir / "backtests" / "results" / ts
    output_dir = Path(output_dir)

    if walk_forward:
        splits = make_splits(start_str, end_str, n_folds=3, test_days=252)
        fold_results = run_walk_forward(config, tickers, splits, bars_cache=bars)
        if not fold_results:
            click.echo("Walk-forward produced no results.")
            raise SystemExit(1)
        agg = aggregate_fold_metrics(fold_results)
        recommendation = write_promotion_report(
            agg,
            fold_results,
            output_dir / "promotion_report.md",
        )
        (output_dir / "walk_forward_results.json").write_text(
            json.dumps({"aggregate": agg, "folds": fold_results}, indent=2),
        )
        click.echo(f"Walk-forward results and promotion report written to {output_dir}")
        click.echo(f"Recommendation: {recommendation}")
        click.echo(json.dumps(agg, indent=2))
        return

    engine = BacktestEngine(config, seed=config["seed"])
    result = engine.run(bars, benchmark=benchmark)

    if "error" in result:
        click.echo(json.dumps(result, indent=2))
        raise SystemExit(1)

    engine.export_artifacts(result, output_dir)

    click.echo(f"Results written to {output_dir}")
    click.echo(json.dumps(result.get("metrics", {}), indent=2))
