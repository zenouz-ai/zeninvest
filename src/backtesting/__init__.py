"""Backtesting engine: historical replay with deterministic policy and paper broker."""

from src.backtesting.engine import BacktestEngine
from src.backtesting.broker import PaperBroker
from src.backtesting.metrics import compute_metrics

__all__ = ["BacktestEngine", "PaperBroker", "compute_metrics"]
