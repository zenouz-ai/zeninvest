"""Mean reversion strategy — buy oversold with sound fundamentals."""

from dataclasses import dataclass
from typing import Any


@dataclass
class MeanReversionSignal:
    """Signal from mean reversion strategy."""
    ticker: str
    action: str  # BUY, SELL, HOLD
    score: float  # 0-100
    reasoning: str
    indicators: dict[str, Any]
    fundamentals: dict[str, Any]


def evaluate_mean_reversion(
    ticker: str,
    indicators: dict[str, Any],
    fundamentals: dict[str, Any],
    sector_avg_pe: float | None = None,
    current_holding: bool = False,
) -> MeanReversionSignal:
    """Evaluate mean reversion signals.

    BUY: RSI<30, below lower BB, IF fundamentals sound (P/E < sector avg,
         positive earnings, debt/equity < 1.5).
    SELL: price at 20-day MA or RSI>60.
    """
    if "error" in indicators:
        return MeanReversionSignal(
            ticker=ticker, action="HOLD", score=0,
            reasoning="Insufficient indicator data",
            indicators=indicators, fundamentals=fundamentals,
        )

    rsi = indicators.get("rsi_14", 50)
    below_lower_bb = indicators.get("below_lower_bb", False)
    current_price = indicators.get("current_price", 0)
    ma_20 = indicators.get("ma_20", 0)
    volume_ratio_20 = indicators.get("volume_sma_ratio_20")

    # Fundamentals
    pe = fundamentals.get("trailing_pe")
    earnings_growth = fundamentals.get("earnings_growth")
    debt_equity = fundamentals.get("debt_equity")

    score = 0.0
    reasons: list[str] = []

    # SELL signals for existing holdings
    if current_holding:
        sell_reasons: list[str] = []
        if ma_20 > 0 and current_price >= ma_20:
            sell_reasons.append(f"Price reached 20-day MA ({ma_20:.2f})")
        if rsi > 60:
            sell_reasons.append(f"RSI recovered ({rsi:.1f}>60)")

        if sell_reasons:
            return MeanReversionSignal(
                ticker=ticker,
                action="SELL",
                score=max(60, min(100, len(sell_reasons) * 35)),
                reasoning="Mean reversion target: " + "; ".join(sell_reasons),
                indicators=indicators,
                fundamentals=fundamentals,
            )

    # BUY signals — oversold with fundamental support
    if rsi < 30:
        score += 30
        reasons.append(f"RSI oversold ({rsi:.1f}<30)")
    elif rsi < 40:
        score += 15
        reasons.append(f"RSI low ({rsi:.1f})")

    if below_lower_bb:
        score += 25
        reasons.append("Below lower Bollinger Band")

    if volume_ratio_20 is not None:
        if below_lower_bb and volume_ratio_20 >= 1.2:
            score += 10
            reasons.append(f"Oversold on above-average volume ({volume_ratio_20:.2f}x avg)")
        elif volume_ratio_20 < 0.5:
            score -= 10
            reasons.append(f"Volume below 50% avg ({volume_ratio_20:.2f}x)")

    # Fundamental checks
    fundamental_ok = True

    if pe is not None:
        if sector_avg_pe and pe < sector_avg_pe:
            score += 15
            reasons.append(f"P/E {pe:.1f} below sector avg {sector_avg_pe:.1f}")
        elif pe is not None and pe > 50:
            fundamental_ok = False
            reasons.append(f"P/E too high ({pe:.1f})")

    if earnings_growth is not None and earnings_growth > 0:
        score += 10
        reasons.append(f"Positive earnings growth ({earnings_growth:.1%})")
    elif earnings_growth is not None and earnings_growth < -0.2:
        fundamental_ok = False
        reasons.append(f"Earnings declining ({earnings_growth:.1%})")

    if debt_equity is not None:
        if debt_equity < 1.5:
            score += 10
            reasons.append(f"D/E ratio OK ({debt_equity:.1f})")
        else:
            fundamental_ok = False
            reasons.append(f"High debt ({debt_equity:.1f}>1.5)")

    if not fundamental_ok:
        score *= 0.3  # Heavily penalize bad fundamentals

    score = max(0, min(100, score))
    action = "BUY" if score >= 70 and rsi < 35 and fundamental_ok else "HOLD"

    return MeanReversionSignal(
        ticker=ticker,
        action=action,
        score=score,
        reasoning=" | ".join(reasons) if reasons else "No mean reversion opportunity",
        indicators=indicators,
        fundamentals=fundamentals,
    )
