"""Universal Opportunity Value (UOV) scoring across cycle decisions."""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.data.database import get_session
from src.data.models import OpportunityScoreSnapshot
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("opportunity_scorer")


@dataclass
class OpportunityScore:
    """Scored opportunity for one ticker in a cycle."""

    ticker: str
    action: str
    stage: str
    is_tradable: bool
    uov_raw: float
    uov_z: float
    uov_final: float
    uov_ewma: float
    previous_uov_ewma: float
    reason: str
    risk_verdict: str | None = None
    moderation_consensus: str | None = None
    final_allocation_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "action": self.action,
            "stage": self.stage,
            "is_tradable": self.is_tradable,
            "uov_raw": round(self.uov_raw, 4),
            "uov_z": round(self.uov_z, 4),
            "uov_final": round(self.uov_final, 4),
            "uov_ewma": round(self.uov_ewma, 4),
            "previous_uov_ewma": round(self.previous_uov_ewma, 4),
            "risk_verdict": self.risk_verdict,
            "moderation_consensus": self.moderation_consensus,
            "reason": self.reason,
            "final_allocation_pct": self.final_allocation_pct,
        }


class OpportunityScorer:
    """Compute and persist UOV scores from strategy/moderation/risk outcomes."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def score_cycle(
        self,
        cycle_id: str,
        evaluations: list[dict[str, Any]],
        sub_results: dict[str, Any],
        stocks_data: list[dict[str, Any]],
        per_ticker_news: dict[str, str],
    ) -> list[OpportunityScore]:
        """Compute UOV scores for all evaluated tickers and persist snapshots."""
        if not evaluations:
            return []

        momentum_map = {s.ticker: float(s.score) for s in sub_results.get("momentum", [])}
        mean_reversion_map = {s.ticker: float(s.score) for s in sub_results.get("mean_reversion", [])}
        factor_map = {
            s.ticker: {
                "composite": float(s.composite_score),
                "quality": float(s.quality_score),
                "value": float(s.value_score),
            }
            for s in sub_results.get("factor", [])
        }
        stock_map = {s.get("ticker", ""): s for s in stocks_data}

        weights = self.settings.opportunity_weights
        penalties = self.settings.opportunity_penalties
        alpha = self._ewma_alpha(self.settings.opportunity_ewma_half_life_cycles)

        session = get_session()
        try:
            previous_ewma = self._get_previous_ewma(
                session=session,
                tickers=[e.get("ticker", "") for e in evaluations],
            )

            raws: list[float] = []
            feature_rows: list[dict[str, Any]] = []

            for evaluation in evaluations:
                ticker = evaluation.get("ticker", "")
                decision = evaluation.get("decision", {})
                moderation = evaluation.get("moderation", {}) or {}

                factor = factor_map.get(ticker, {})
                stock = stock_map.get(ticker, {})
                fundamentals = stock.get("fundamentals", {})

                momentum_score = momentum_map.get(ticker)
                mean_reversion_score = mean_reversion_map.get(ticker)
                factor_composite = factor.get("composite")
                factor_quality = factor.get("quality")
                factor_value = factor.get("value")
                conviction = self._safe_float(decision.get("conviction"))
                holding_period = str(decision.get("expected_holding_period", ""))

                gpt_verdict = ((moderation.get("gpt4o_verdict") or {}).get("verdict") or "").upper()
                gemini = moderation.get("gemini_verdict") or {}
                gemini_growth = self._safe_float(gemini.get("growth_score"))
                gemini_risk = self._safe_float(gemini.get("risk_score"))
                gemini_conf = self._safe_float(gemini.get("confidence_score"))

                yf_ticker = t212_to_yf(ticker)
                news_sentiment_score = self._extract_news_sentiment(
                    per_ticker_news.get(yf_ticker, ""),
                    str(decision.get("news_sentiment_summary", "")),
                )
                market_cap = self._safe_float(fundamentals.get("market_cap"))

                raw = (
                    weights["momentum"] * self._center_100(momentum_score)
                    + weights["mean_reversion"] * self._center_100(mean_reversion_score)
                    + weights["factor_composite"] * self._center_100(factor_composite)
                    + weights["factor_quality"] * self._center_100(factor_quality)
                    + weights["factor_value"] * self._center_100(factor_value)
                    + weights["conviction"] * self._center_100(conviction)
                    + weights["expected_holding_period"] * self._holding_period_score(holding_period)
                    + weights["gpt_verdict"] * self._gpt_verdict_score(gpt_verdict)
                    + weights["gemini_growth_vs_risk"] * self._gemini_growth_risk_score(gemini_growth, gemini_risk)
                    + weights["gemini_confidence"] * self._center_10(gemini_conf)
                    + weights["news_sentiment"] * news_sentiment_score
                    + weights["market_cap"] * self._market_cap_score(market_cap)
                )

                raws.append(raw)
                feature_rows.append(
                    {
                        "ticker": ticker,
                        "momentum_score": momentum_score,
                        "mean_reversion_score": mean_reversion_score,
                        "factor_composite_score": factor_composite,
                        "factor_quality_score": factor_quality,
                        "factor_value_score": factor_value,
                        "conviction": int(conviction) if conviction is not None else None,
                        "expected_holding_period": holding_period,
                        "gpt_verdict": gpt_verdict or None,
                        "gemini_growth_score": int(gemini_growth) if gemini_growth is not None else None,
                        "gemini_risk_score": int(gemini_risk) if gemini_risk is not None else None,
                        "gemini_confidence_score": int(gemini_conf) if gemini_conf is not None else None,
                        "news_sentiment_score": news_sentiment_score,
                        "market_cap": market_cap,
                        "uov_raw": raw,
                    },
                )

            z_scores = self._z_scores(raws)
            scored: list[OpportunityScore] = []

            for idx, evaluation in enumerate(evaluations):
                ticker = evaluation.get("ticker", "")
                stage = evaluation.get("stage", "unrated")
                action = evaluation.get("action", "HOLD")
                risk_verdict = evaluation.get("risk_verdict")
                moderation_consensus = evaluation.get("moderation_consensus")
                final_allocation_pct = self._safe_float(evaluation.get("final_allocation_pct"))
                reason = str(evaluation.get("reason", ""))

                is_tradable = action == "BUY" and stage in ("approved", "risk_resize")
                stage_penalty = self._stage_penalty(
                    stage=stage,
                    risk_verdict=risk_verdict,
                    penalties=penalties,
                )
                uov_final = z_scores[idx] + stage_penalty
                if not is_tradable:
                    uov_final = min(uov_final, 0.0)

                prev = previous_ewma.get(ticker, 0.0)
                ewma = alpha * uov_final + (1 - alpha) * prev

                score = OpportunityScore(
                    ticker=ticker,
                    action=action,
                    stage=stage,
                    is_tradable=is_tradable,
                    uov_raw=raws[idx],
                    uov_z=z_scores[idx],
                    uov_final=uov_final,
                    uov_ewma=ewma,
                    previous_uov_ewma=prev,
                    reason=reason,
                    risk_verdict=risk_verdict,
                    moderation_consensus=moderation_consensus,
                    final_allocation_pct=final_allocation_pct,
                )
                scored.append(score)

                features = feature_rows[idx]
                session.add(
                    OpportunityScoreSnapshot(
                        timestamp=datetime.now(timezone.utc),
                        cycle_id=cycle_id,
                        ticker=ticker,
                        action=action,
                        stage=stage,
                        is_tradable=is_tradable,
                        uov_raw=score.uov_raw,
                        uov_z=score.uov_z,
                        uov_final=score.uov_final,
                        uov_ewma=score.uov_ewma,
                        previous_uov_ewma=score.previous_uov_ewma,
                        momentum_score=features["momentum_score"],
                        mean_reversion_score=features["mean_reversion_score"],
                        factor_composite_score=features["factor_composite_score"],
                        factor_quality_score=features["factor_quality_score"],
                        factor_value_score=features["factor_value_score"],
                        conviction=features["conviction"],
                        expected_holding_period=features["expected_holding_period"] or None,
                        gpt_verdict=features["gpt_verdict"],
                        gemini_growth_score=features["gemini_growth_score"],
                        gemini_risk_score=features["gemini_risk_score"],
                        gemini_confidence_score=features["gemini_confidence_score"],
                        moderation_consensus=moderation_consensus,
                        risk_verdict=risk_verdict,
                        news_sentiment_score=features["news_sentiment_score"],
                        market_cap=features["market_cap"],
                        reason=reason[:1000],
                    ),
                )

            session.commit()
            scored.sort(key=lambda s: s.uov_ewma, reverse=True)
            return scored
        except Exception as exc:
            session.rollback()
            logger.error(f"Failed to compute/persist opportunity scores: {exc}")
            return []
        finally:
            session.close()

    def build_swap_context(self, existing_tickers: set[str], limit: int = 5) -> str:
        """Build optional prompt context from prior-cycle UOV snapshots."""
        if not existing_tickers:
            return ""

        session = get_session()
        try:
            held_scores: list[tuple[str, float]] = []
            for ticker in existing_tickers:
                latest = (
                    session.query(OpportunityScoreSnapshot)
                    .filter(OpportunityScoreSnapshot.ticker == ticker)
                    .order_by(OpportunityScoreSnapshot.timestamp.desc())
                    .first()
                )
                if latest:
                    held_scores.append((ticker, float(latest.uov_ewma)))

            if not held_scores:
                return ""

            held_scores.sort(key=lambda x: x[1])
            weakest_ticker, weakest_score = held_scores[0]

            queued = (
                session.query(OpportunityScoreSnapshot)
                .filter(
                    OpportunityScoreSnapshot.action == "BUY",
                    OpportunityScoreSnapshot.is_tradable.is_(True),  # noqa: E712
                )
                .order_by(OpportunityScoreSnapshot.timestamp.desc())
                .limit(100)
                .all()
            )

            latest_by_ticker: dict[str, OpportunityScoreSnapshot] = {}
            for row in queued:
                ticker_str = str(row.ticker)
                if ticker_str in existing_tickers:
                    continue
                if ticker_str not in latest_by_ticker:
                    latest_by_ticker[ticker_str] = row

            ranked = sorted(
                latest_by_ticker.values(),
                key=lambda r: float(r.uov_ewma),
                reverse=True,
            )[:limit]

            if not ranked:
                return ""

            lines = [
                "## PRIOR UOV SWAP WATCHLIST",
                f"Weakest held UOV EWMA: {weakest_ticker} ({weakest_score:.2f})",
            ]
            for row in ranked:
                uplift = float(row.uov_ewma) - weakest_score
                lines.append(
                    f"- {row.ticker}: UOV EWMA {float(row.uov_ewma):.2f} "
                    f"(vs weakest +{uplift:.2f})"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.warning(f"Unable to build swap context: {exc}")
            return ""
        finally:
            session.close()

    def get_latest_ewma_map(self, tickers: set[str]) -> dict[str, float]:
        """Return latest UOV EWMA values for tickers from persisted snapshots."""
        if not tickers:
            return {}
        session = get_session()
        try:
            return self._get_previous_ewma(session=session, tickers=list(tickers))
        finally:
            session.close()

    @staticmethod
    def _get_previous_ewma(session, tickers: list[str]) -> dict[str, float]:  # type: ignore[no-untyped-def]
        from sqlalchemy import func

        unique = {t for t in tickers if t}
        if not unique:
            return {}

        # Single query: latest timestamp per ticker, then fetch EWMA for those rows
        subq = (
            session.query(
                OpportunityScoreSnapshot.ticker,
                func.max(OpportunityScoreSnapshot.timestamp).label("max_ts"),
            )
            .filter(OpportunityScoreSnapshot.ticker.in_(unique))
            .group_by(OpportunityScoreSnapshot.ticker)
            .subquery()
        )

        rows = (
            session.query(OpportunityScoreSnapshot.ticker, OpportunityScoreSnapshot.uov_ewma)
            .join(
                subq,
                (OpportunityScoreSnapshot.ticker == subq.c.ticker)
                & (OpportunityScoreSnapshot.timestamp == subq.c.max_ts),
            )
            .all()
        )

        return {str(row.ticker): float(row.uov_ewma) for row in rows}

    @staticmethod
    def _z_scores(values: list[float]) -> list[float]:
        if not values:
            return []
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        if std < 1e-9:
            return [0.0 for _ in values]
        return [(v - mean) / std for v in values]

    @staticmethod
    def _center_100(value: float | None) -> float:
        if value is None:
            return 0.0
        return max(-1.0, min(1.0, (value - 50.0) / 50.0))

    @staticmethod
    def _center_10(value: float | None) -> float:
        if value is None:
            return 0.0
        return max(-1.0, min(1.0, (value - 5.0) / 5.0))

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _gpt_verdict_score(verdict: str) -> float:
        if verdict == "AGREE":
            return 1.0
        if verdict == "MODIFY":
            return 0.2
        if verdict == "DISAGREE":
            return -1.0
        return 0.0

    @staticmethod
    def _gemini_growth_risk_score(growth: float | None, risk: float | None) -> float:
        if growth is None or risk is None:
            return 0.0
        return max(-1.0, min(1.0, (growth - risk) / 10.0))

    @staticmethod
    def _market_cap_score(market_cap: float | None) -> float:
        if market_cap is None or market_cap <= 0:
            return 0.0
        log_cap = math.log10(market_cap)
        return max(-1.0, min(1.0, (log_cap - 10.5) / 2.5))

    @staticmethod
    def _holding_period_score(text: str) -> float:
        if not text:
            return 0.0
        lower = text.lower()
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", lower)]
        if not nums:
            return 0.0
        avg = sum(nums) / len(nums)
        if "week" in lower:
            months = avg / 4.0
        elif "year" in lower:
            months = avg * 12.0
        else:
            months = avg

        if months < 1:
            return -0.4
        if months <= 3:
            return 0.0
        if months <= 6:
            return 0.25
        if months <= 12:
            return 0.4
        return 0.2

    @staticmethod
    def _extract_news_sentiment(per_ticker_news: str, summary_text: str) -> float:
        if per_ticker_news:
            match = re.search(r"Ticker avg sentiment:\s*([+-]?\d+(?:\.\d+)?)", per_ticker_news)
            if match:
                score = float(match.group(1))
                return max(-1.0, min(1.0, score))

        lower = summary_text.lower()
        if not lower:
            return 0.0
        bullish_hits = sum(1 for kw in ("bullish", "positive", "upside", "tailwind") if kw in lower)
        bearish_hits = sum(1 for kw in ("bearish", "negative", "downside", "headwind", "risk") if kw in lower)
        if bullish_hits == bearish_hits:
            return 0.0
        return max(-1.0, min(1.0, (bullish_hits - bearish_hits) / 4.0))

    @staticmethod
    def _ewma_alpha(half_life_cycles: float) -> float:
        half_life = max(1.0, half_life_cycles)
        return 1.0 - math.pow(0.5, 1.0 / half_life)

    @staticmethod
    def _stage_penalty(stage: str, risk_verdict: str | None, penalties: dict[str, float]) -> float:
        if stage == "strategy_hold":
            return penalties["strategy_hold"]
        if stage == "strategy_queued":
            return penalties.get("strategy_queued", -0.6)
        if stage == "moderation_blocked":
            return penalties["moderation_blocked"]
        if stage == "risk_reject":
            return penalties["risk_reject"]
        penalty = 0.0
        if risk_verdict == "RESIZE":
            penalty += penalties["risk_resize"]
        if stage == "unrated":
            penalty += penalties["unrated"]
        return penalty
