"""Factor strategy — composite scoring: Value(30%) + Quality(30%) + Momentum(40%)."""

from dataclasses import dataclass
from typing import Any


@dataclass
class FactorScore:
    """Factor-based composite score for a stock."""
    ticker: str
    composite_score: float  # 0-100
    value_score: float
    quality_score: float
    momentum_score: float
    reasoning: str
    components: dict[str, Any]


def calculate_factor_score(
    ticker: str,
    fundamentals: dict[str, Any],
    indicators: dict[str, Any],
    relative_strength: float | None,
    six_month_return: float | None = None,
) -> FactorScore:
    """Calculate composite factor score.

    Composite = Value(30%) + Quality(30%) + Momentum(40%).

    Value: low P/E, P/B.
    Quality: high ROE, stable margins, low debt.
    Momentum: 6-month return, earnings momentum.
    """
    components: dict[str, Any] = {}
    reasons: list[str] = []

    # --- VALUE (30%) ---
    value_score = 50.0  # neutral default
    pe = fundamentals.get("trailing_pe")
    pb = fundamentals.get("pb_ratio")

    if pe is not None:
        if pe < 0:
            value_score -= 20  # Negative earnings
            reasons.append(f"Negative P/E ({pe:.1f})")
        elif pe < 15:
            value_score += 30
            reasons.append(f"Low P/E ({pe:.1f})")
        elif pe < 25:
            value_score += 10
        elif pe > 40:
            value_score -= 20
            reasons.append(f"High P/E ({pe:.1f})")
        components["pe"] = pe

    if pb is not None:
        if pb < 1.5:
            value_score += 20
            reasons.append(f"Low P/B ({pb:.1f})")
        elif pb < 3:
            value_score += 5
        elif pb > 10:
            value_score -= 15
        components["pb"] = pb

    value_score = max(0, min(100, value_score))

    # --- QUALITY (30%) ---
    quality_score = 50.0
    roe = fundamentals.get("roe")
    margin = fundamentals.get("profit_margin")
    debt_eq = fundamentals.get("debt_equity")

    if roe is not None:
        if roe > 0.20:
            quality_score += 25
            reasons.append(f"High ROE ({roe:.1%})")
        elif roe > 0.10:
            quality_score += 10
        elif roe < 0:
            quality_score -= 20
        components["roe"] = roe

    if margin is not None:
        if margin > 0.20:
            quality_score += 15
            reasons.append(f"Strong margins ({margin:.1%})")
        elif margin > 0.10:
            quality_score += 5
        elif margin < 0:
            quality_score -= 15
        components["margin"] = margin

    if debt_eq is not None:
        if debt_eq < 0.5:
            quality_score += 15
            reasons.append(f"Low debt ({debt_eq:.1f})")
        elif debt_eq < 1.0:
            quality_score += 5
        elif debt_eq > 2.0:
            quality_score -= 15
        components["debt_equity"] = debt_eq

    quality_score = max(0, min(100, quality_score))

    # --- MOMENTUM (40%) ---
    momentum_score = 50.0
    earnings_mom = fundamentals.get("earnings_momentum_qoq")

    if six_month_return is not None:
        if six_month_return > 0.20:
            momentum_score += 25
            reasons.append(f"Strong 6mo return ({six_month_return:.1%})")
        elif six_month_return > 0.10:
            momentum_score += 15
        elif six_month_return > 0:
            momentum_score += 5
        elif six_month_return < -0.10:
            momentum_score -= 15
        components["six_month_return"] = six_month_return

    if relative_strength is not None:
        if relative_strength > 1.1:
            momentum_score += 20
            reasons.append(f"RS vs S&P: {relative_strength:.2f}")
        elif relative_strength > 1.0:
            momentum_score += 10
        elif relative_strength < 0.9:
            momentum_score -= 10
        components["relative_strength"] = relative_strength

    if earnings_mom is not None:
        if earnings_mom > 0.1:
            momentum_score += 15
            reasons.append(f"Earnings momentum: {earnings_mom:.1%}")
        elif earnings_mom > 0:
            momentum_score += 5
        elif earnings_mom < -0.1:
            momentum_score -= 10
        components["earnings_momentum"] = earnings_mom

    momentum_score = max(0, min(100, momentum_score))

    # --- COMPOSITE ---
    composite = (
        value_score * 0.30 +
        quality_score * 0.30 +
        momentum_score * 0.40
    )
    composite = max(0, min(100, composite))

    return FactorScore(
        ticker=ticker,
        composite_score=round(composite, 1),
        value_score=round(value_score, 1),
        quality_score=round(quality_score, 1),
        momentum_score=round(momentum_score, 1),
        reasoning=" | ".join(reasons) if reasons else "Average factor profile",
        components=components,
    )


def rank_by_factor(scores: list[FactorScore], top_n: int = 10) -> list[FactorScore]:
    """Rank stocks by composite factor score, return top N."""
    sorted_scores = sorted(scores, key=lambda s: s.composite_score, reverse=True)
    return sorted_scores[:top_n]
