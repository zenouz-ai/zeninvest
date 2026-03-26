"""Moderation panel — Investment Committee consensus logic.

Passes the full market context (indicators, fundamentals, macro, sub-strategy
scores, analyst data, news sentiment) to both moderators for independent review.
"""

import json
from datetime import datetime, timezone
from typing import Any

from src.agents.moderation import gemini_mod, openai_mod
from src.data.database import get_session
from src.data.models import ModerationLog
from src.utils.config import get_settings
from src.utils.cost_tracker import DegradationLevel, get_degradation_level
from src.utils.logger import get_logger

logger = get_logger("moderation_panel")


class ModerationResult:
    """Result of the moderation panel review."""

    def __init__(
        self,
        ticker: str,
        consensus: str,
        strategy_verdict: str,
        gpt4o_verdict: dict[str, Any] | None,
        gemini_verdict: dict[str, Any] | None,
        moderators_available: int,
        caution_flag: bool = False,
    ) -> None:
        self.ticker = ticker
        self.consensus = consensus  # APPROVED, BLOCKED, CAUTION
        self.strategy_verdict = strategy_verdict
        self.gpt4o_verdict = gpt4o_verdict
        self.gemini_verdict = gemini_verdict
        self.moderators_available = moderators_available
        self.caution_flag = caution_flag

    @property
    def gpt_score(self) -> int | float | None:
        """Extract score from GPT-4o verdict (confidence_score if present)."""
        if not isinstance(self.gpt4o_verdict, dict):
            return None
        return self.gpt4o_verdict.get("score") or self.gpt4o_verdict.get("confidence_score")

    @property
    def gemini_score(self) -> int | float | None:
        """Extract score from Gemini verdict."""
        if not isinstance(self.gemini_verdict, dict):
            return None
        return self.gemini_verdict.get("score") or self.gemini_verdict.get("confidence_score")

    @property
    def gpt_reasoning(self) -> str | None:
        """Extract reasoning from GPT-4o verdict."""
        if not isinstance(self.gpt4o_verdict, dict):
            return None
        return self.gpt4o_verdict.get("reasoning")

    @property
    def gemini_reasoning(self) -> str | None:
        """Extract reasoning from Gemini verdict."""
        if not isinstance(self.gemini_verdict, dict):
            return None
        return self.gemini_verdict.get("reasoning") or self.gemini_verdict.get("assessment")

    @property
    def modifications(self) -> dict[str, Any] | None:
        """Extract the most conservative modification from moderator MODIFY verdicts (audit fix C-1)."""
        mods: list[dict[str, Any]] = []
        for label, verdict in (("gpt-4o", self.gpt4o_verdict), ("gemini", self.gemini_verdict)):
            if not isinstance(verdict, dict):
                if verdict is not None:
                    logger.warning(
                        "Ignoring malformed %s verdict for %s while extracting modifications: type=%s",
                        label,
                        self.ticker,
                        type(verdict).__name__,
                    )
                continue
            modifications = verdict.get("modifications")
            if verdict.get("verdict") != "MODIFY" or not modifications:
                continue
            if not isinstance(modifications, dict):
                logger.warning(
                    "Ignoring malformed %s modifications for %s while extracting modifications: type=%s",
                    label,
                    self.ticker,
                    type(modifications).__name__,
                )
                continue
            mods.append(modifications)
        if not mods:
            return None
        # Use the most conservative (lowest) allocation suggestion
        alloc_suggestions = [m["target_allocation_pct"] for m in mods if m.get("target_allocation_pct")]
        stop_suggestions = [m["stop_loss_pct"] for m in mods if m.get("stop_loss_pct")]
        result: dict[str, Any] = {}
        if alloc_suggestions:
            result["target_allocation_pct"] = min(alloc_suggestions)
        if stop_suggestions:
            # Most conservative = smallest (closest to 0, tightest stop)
            result["stop_loss_pct"] = max(stop_suggestions)  # e.g. -5 is tighter than -8
        return result if result else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "consensus": self.consensus,
            "strategy_verdict": self.strategy_verdict,
            "gpt4o_verdict": self.gpt4o_verdict,
            "gemini_verdict": self.gemini_verdict,
            "moderators_available": self.moderators_available,
            "caution_flag": self.caution_flag,
            "modifications": self.modifications,
        }


class ModerationPanel:
    """Investment Committee — multi-LLM review system."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def review_trade(
        self,
        trade_proposal: dict[str, Any],
        portfolio_context: str,
        market_context: dict[str, Any],
        conviction: int,
        cycle_id: str,
        research_executor=None,
    ) -> ModerationResult:
        """Run the full moderation panel on a trade proposal.

        Args:
            trade_proposal: Strategy agent's decision for a single stock.
            portfolio_context: Current portfolio state description.
            market_context: Rich dict with indicators, fundamentals, macro,
                          sub-strategy scores, analyst data, news sentiment.
            conviction: Strategy conviction score (0-100).
            cycle_id: Cycle identifier for cost tracking and logging.
        """
        ticker = trade_proposal.get("ticker", "UNKNOWN")
        degradation = get_degradation_level()

        # Determine which moderators are available
        use_gpt4o = degradation in (DegradationLevel.FULL, DegradationLevel.NO_GEMINI)
        use_gemini = degradation in (DegradationLevel.FULL, DegradationLevel.NO_GPT4O)

        if degradation == DegradationLevel.NO_STRATEGY:
            # Both moderators unavailable
            use_gpt4o = False
            use_gemini = False
        elif degradation == DegradationLevel.HALTED:
            use_gpt4o = False
            use_gemini = False

        # Get moderator verdicts
        gpt4o_result = None
        gemini_result = None

        if use_gpt4o:
            gpt4o_result = openai_mod.review_trade(
                trade_proposal, portfolio_context, market_context, cycle_id,
                research_executor=research_executor if self.settings.skeptic_research_enabled else None,
            )
            if not gpt4o_result.get("available", False):
                gpt4o_result = None

        if use_gemini:
            gemini_result = gemini_mod.review_trade(
                trade_proposal, portfolio_context, market_context, cycle_id,
                research_executor=research_executor if self.settings.risk_research_enabled else None,
            )
            if not gemini_result.get("available", False):
                gemini_result = None

        # Count available moderators
        moderators_available = sum([
            1 if gpt4o_result else 0,
            1 if gemini_result else 0,
        ])

        # Determine consensus
        consensus = self._determine_consensus(
            strategy_verdict="AGREE",  # Strategy always agrees with its own proposal
            gpt4o_result=gpt4o_result,
            gemini_result=gemini_result,
            conviction=conviction,
            moderators_available=moderators_available,
        )

        result = ModerationResult(
            ticker=ticker,
            consensus=consensus,
            strategy_verdict="AGREE",
            gpt4o_verdict=gpt4o_result,
            gemini_verdict=gemini_result,
            moderators_available=moderators_available,
            caution_flag=(consensus == "CAUTION"),
        )

        # Log to database
        self._log_moderation(result, cycle_id)

        return result

    def _determine_consensus(
        self,
        strategy_verdict: str,
        gpt4o_result: dict[str, Any] | None,
        gemini_result: dict[str, Any] | None,
        conviction: int,
        moderators_available: int,
    ) -> str:
        """Determine consensus from all verdicts.

        Rules:
        - 3/3 AGREE → APPROVED
        - 2/3 AGREE → CAUTION (proceed with flag)
        - 2/3 DISAGREE → BLOCKED
        - HIGH_RISK + both moderators DISAGREE → BLOCKED
        - HIGH_RISK + one DISAGREE → CAUTION (proceed with flag)
        - 1 moderator: require AGREE + conviction > 60
        - 0 moderators: conviction > 70 only
        """
        settings = self.settings

        gpt4o_verdict = gpt4o_result.get("verdict", "SKIP") if gpt4o_result else "SKIP"
        gemini_verdict = gemini_result.get("verdict", "SKIP") if gemini_result else "SKIP"

        # Check for high risk flag from Gemini
        high_risk = False
        if gemini_result and gemini_result.get("high_risk_flag"):
            high_risk = True
        if gemini_result:
            risk_score = gemini_result.get("risk_score", 0)
            growth_score = gemini_result.get("growth_score", 0)
            if risk_score > growth_score + 2:
                high_risk = True

        # Fallback: 0 moderators
        if moderators_available == 0:
            min_conv = settings.min_conviction_no_moderators
            if conviction >= min_conv:
                logger.info(f"No moderators available. Conviction {conviction} >= {min_conv}, proceeding.")
                return "APPROVED"
            else:
                logger.warning(f"No moderators. Conviction {conviction} < {min_conv}, blocking.")
                return "BLOCKED"

        # Fallback: 1 moderator
        if moderators_available == 1:
            min_conv = settings.min_conviction_one_moderator
            active_verdict = gpt4o_verdict if gpt4o_result else gemini_verdict
            if active_verdict == "AGREE" and conviction >= min_conv:
                return "APPROVED"
            elif active_verdict == "DISAGREE":
                return "BLOCKED"
            else:
                return "CAUTION"

        # 2 moderators available
        # Count MODIFY as conditional AGREE (audit fix C-1)
        verdicts = [strategy_verdict, gpt4o_verdict, gemini_verdict]
        agree_count = verdicts.count("AGREE") + verdicts.count("MODIFY")
        disagree_count = verdicts.count("DISAGREE")

        # High risk + both moderators disagree → BLOCKED
        if high_risk and disagree_count >= 2:
            logger.warning("HIGH RISK + BOTH DISAGREE → BLOCKED")
            return "BLOCKED"

        # High risk + one disagree → proceed with caution
        if high_risk and disagree_count == 1:
            logger.warning("HIGH RISK + 1 DISAGREE → CAUTION")
            return "CAUTION"

        if agree_count == 3:
            return "APPROVED"
        elif agree_count >= 2:
            return "CAUTION"
        elif disagree_count >= 2:
            return "BLOCKED"
        else:
            return "CAUTION"

    def _log_moderation(self, result: ModerationResult, cycle_id: str) -> None:
        """Log moderation results to database."""
        session = get_session()
        try:
            # Log strategy verdict
            session.add(ModerationLog(
                timestamp=datetime.now(timezone.utc),
                cycle_id=cycle_id,
                ticker=result.ticker,
                moderator="strategy",
                verdict=result.strategy_verdict,
                reasoning="Primary strategy proposal",
                consensus=result.consensus,
            ))

            # Log GPT-4o verdict (audit fix H-4: include consensus on all rows)
            if result.gpt4o_verdict:
                session.add(ModerationLog(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=result.ticker,
                    moderator="gpt-4o",
                    verdict=result.gpt4o_verdict.get("verdict", "SKIP"),
                    reasoning=result.gpt4o_verdict.get("reasoning"),
                    consensus=result.consensus,
                ))

            # Log Gemini verdict (audit fix H-4: include consensus on all rows)
            if result.gemini_verdict:
                session.add(ModerationLog(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=result.ticker,
                    moderator=result.gemini_verdict.get("moderator", "gemini"),
                    verdict=result.gemini_verdict.get("verdict", "SKIP"),
                    reasoning=result.gemini_verdict.get("assessment"),
                    consensus=result.consensus,
                    growth_score=result.gemini_verdict.get("growth_score"),
                    risk_score=result.gemini_verdict.get("risk_score"),
                    confidence_score=result.gemini_verdict.get("confidence_score"),
                ))

            session.commit()
        except Exception as e:
            logger.error(f"Failed to log moderation: {e}")
            session.rollback()
        finally:
            session.close()
