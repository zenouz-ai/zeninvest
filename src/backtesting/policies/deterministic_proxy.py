"""Deterministic policy: map bar/indicator data to BUY/SELL/HOLD and size (no LLM)."""

from dataclasses import dataclass
from typing import Any


@dataclass
class PolicySignal:
    """Single ticker signal from policy."""
    ticker: str
    action: str  # BUY, SELL, HOLD
    weight: float  # 0-1 allocation weight for BUY
    score: float  # internal score


class DeterministicPolicy:
    """LLM-free policy: simple rules from close vs SMA for backtest reproducibility."""

    def __init__(self, sma_period: int = 20, max_positions: int = 10) -> None:
        self.sma_period = sma_period
        self.max_positions = max_positions

    def run(
        self,
        date,
        bars: dict[str, dict[str, Any]],
        current_positions: set[str],
    ) -> list[PolicySignal]:
        """Produce signals from bar data. Bars must have close and sma (or we compute from history).

        Args:
            date: Current bar date.
            bars: Ticker -> {close, sma, ...} for today.
            current_positions: Tickers we currently hold.

        Returns:
            List of PolicySignal (BUY/SELL/HOLD with weight/score).
        """
        signals: list[PolicySignal] = []
        for ticker, data in bars.items():
            close = float(data.get("close", 0) or 0)
            sma = data.get("sma")
            if sma is None:
                sma = close
            sma = float(sma)
            held = ticker in current_positions

            if close <= 0:
                signals.append(PolicySignal(ticker=ticker, action="HOLD", weight=0.0, score=0.0))
                continue

            # Simple rule: BUY if close > sma and not held; SELL if held and close < sma
            if held:
                if close < sma:
                    signals.append(PolicySignal(ticker=ticker, action="SELL", weight=0.0, score=-1.0))
                else:
                    signals.append(PolicySignal(ticker=ticker, action="HOLD", weight=0.0, score=0.5))
            else:
                if close > sma:
                    # Score by how much above SMA (normalized)
                    score = min(1.0, (close - sma) / sma * 10) if sma else 0.5
                    signals.append(PolicySignal(ticker=ticker, action="BUY", weight=0.1, score=score))
                else:
                    signals.append(PolicySignal(ticker=ticker, action="HOLD", weight=0.0, score=0.0))

        return signals
