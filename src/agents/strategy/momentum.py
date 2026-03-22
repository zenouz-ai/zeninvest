"""Momentum strategy — trend following with technical confirmation."""

from dataclasses import dataclass
from typing import Any


@dataclass
class MomentumSignal:
    """Signal from momentum strategy."""
    ticker: str
    action: str  # BUY, SELL, HOLD
    score: float  # 0-100
    reasoning: str
    indicators: dict[str, Any]


def evaluate_momentum(
    ticker: str,
    indicators: dict[str, Any],
    relative_strength: float | None,
    current_holding: bool = False,
) -> MomentumSignal:
    """Evaluate momentum signals for a stock.

    BUY: above 50-day MA, RSI 50-70, positive MACD crossover, RS>1.0 vs S&P.
    Volume can confirm breakouts via OBV and 20-day average volume ratio.
    SELL: RSI>80 OR below 50-day MA OR MACD bearish crossover.
    """
    if "error" in indicators:
        return MomentumSignal(
            ticker=ticker, action="HOLD", score=0,
            reasoning="Insufficient indicator data", indicators=indicators,
        )

    rsi = indicators.get("rsi_14", 50)
    above_50ma = indicators.get("above_50ma", False)
    macd_bullish = indicators.get("macd_bullish_crossover", False)
    macd_bearish = indicators.get("macd_bearish_crossover", False)
    macd_histogram = indicators.get("macd_histogram", 0)
    volume_ratio_20 = indicators.get("volume_sma_ratio_20")
    obv_rising_5d = indicators.get("obv_rising_5d", False)
    rs = relative_strength or 0.0

    score = 0.0
    reasons: list[str] = []

    # SELL signals (check first for existing holdings)
    if current_holding:
        sell_reasons: list[str] = []
        if rsi > 80:
            sell_reasons.append(f"RSI overbought ({rsi:.1f}>80)")
        if not above_50ma:
            sell_reasons.append("Price below 50-day MA")
        if macd_bearish:
            sell_reasons.append("MACD bearish crossover")

        if sell_reasons:
            return MomentumSignal(
                ticker=ticker,
                action="SELL",
                score=max(60, min(100, len(sell_reasons) * 30)),
                reasoning="Momentum sell: " + "; ".join(sell_reasons),
                indicators=indicators,
            )

    # BUY signals
    if above_50ma:
        score += 25
        reasons.append("Above 50-day MA")

    if 50 <= rsi <= 70:
        score += 25
        reasons.append(f"RSI in sweet spot ({rsi:.1f})")
    elif rsi < 50:
        score -= 10
    elif rsi > 70:
        score += 10
        reasons.append(f"RSI strong ({rsi:.1f})")

    if macd_bullish:
        score += 25
        reasons.append("MACD bullish crossover")
    elif macd_histogram > 0:
        score += 10
        reasons.append("MACD histogram positive")

    if rs > 1.0:
        score += 25
        reasons.append(f"RS vs S&P: {rs:.2f}")
    elif rs > 0.9:
        score += 10
        reasons.append(f"RS near benchmark: {rs:.2f}")

    if volume_ratio_20 is not None:
        if above_50ma and volume_ratio_20 >= 1.5:
            score += 10
            reasons.append(f"High-volume breakout ({volume_ratio_20:.2f}x avg)")
        elif volume_ratio_20 < 0.5:
            score -= 10
            reasons.append(f"Volume below 50% avg ({volume_ratio_20:.2f}x)")

    if obv_rising_5d:
        score += 5
        reasons.append("OBV rising over 5 days")

    score = max(0, min(100, score))
    action = "BUY" if score >= 75 and above_50ma else "HOLD"

    return MomentumSignal(
        ticker=ticker,
        action=action,
        score=score,
        reasoning=" | ".join(reasons) if reasons else "No strong momentum signals",
        indicators=indicators,
    )
