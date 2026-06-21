"""Moderation panel — Investment Committee consensus logic.

Passes the full market context (indicators, fundamentals, macro, sub-strategy
scores, analyst data, news sentiment) to both moderators for independent review.
"""

import json
from datetime import datetime, timezone
from typing import Any

from src.agents.moderation import gemini_mod, openai_mod
from src.agents.strategy.prompts import get_strategy_prompt_hash
from src.data.database import get_session
from src.data.models import ModerationLog
from src.utils.config import get_settings
from src.utils.cost_tracker import DegradationLevel, get_degradation_level
from src.utils.logger import get_logger

logger = get_logger("moderation_panel")


def _format_peer_argument(
    verdict: dict[str, Any] | None,
    *,
    anonymize: bool,
    fallback_label: str,
) -> str:
    """Render one moderator's opening verdict as input for the other's rebuttal turn."""
    if not isinstance(verdict, dict):
        return ""
    name = "A fellow committee analyst" if anonymize else fallback_label
    lines = [f"{name} reached this verdict: {verdict.get('verdict', 'UNKNOWN')}"]
    reasoning = verdict.get("reasoning") or verdict.get("assessment")
    if reasoning:
        lines.append(f"Their reasoning: {reasoning}")
    flags = verdict.get("risk_flags")
    if isinstance(flags, list) and flags:
        lines.append("Risks they flagged: " + ", ".join(str(f) for f in flags))
    for key, label in (("growth_score", "growth"), ("risk_score", "risk"), ("confidence_score", "confidence")):
        if verdict.get(key) is not None:
            lines.append(f"Their {label} score: {verdict[key]}")
    return "\n".join(lines)


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
        debate_rounds: int = 1,
        gpt_verdict_changed: bool | None = None,
        gemini_verdict_changed: bool | None = None,
    ) -> None:
        self.ticker = ticker
        self.consensus = consensus  # APPROVED, BLOCKED, CAUTION
        self.strategy_verdict = strategy_verdict
        self.gpt4o_verdict = gpt4o_verdict
        self.gemini_verdict = gemini_verdict
        self.moderators_available = moderators_available
        self.caution_flag = caution_flag
        # Debate telemetry (for offline benefit measurement over time).
        self.debate_rounds = debate_rounds
        self.gpt_verdict_changed = gpt_verdict_changed
        self.gemini_verdict_changed = gemini_verdict_changed

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
        research_executor: Any = None,
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

        # Get moderator verdicts (run concurrently when both are enabled).
        def _run_gpt4o() -> dict[str, Any] | None:
            res = openai_mod.review_trade(
                trade_proposal, portfolio_context, market_context, cycle_id,
                research_executor=research_executor if self.settings.skeptic_research_enabled else None,
            )
            return res if res.get("available", False) else None

        def _run_gemini() -> dict[str, Any] | None:
            res = gemini_mod.review_trade(
                trade_proposal, portfolio_context, market_context, cycle_id,
                research_executor=research_executor if self.settings.risk_research_enabled else None,
            )
            return res if res.get("available", False) else None

        gpt4o_result = None
        gemini_result = None

        if use_gpt4o and use_gemini and self.settings.parallel_moderation_enabled:
            # Both moderators run in parallel; one failing must not kill the other.
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as executor:
                gpt4o_future = executor.submit(_run_gpt4o)
                gemini_future = executor.submit(_run_gemini)
                try:
                    gpt4o_result = gpt4o_future.result()
                except Exception as exc:
                    logger.error(f"GPT-4o moderator failed for {ticker}: {exc}")
                try:
                    gemini_result = gemini_future.result()
                except Exception as exc:
                    logger.error(f"Gemini moderator failed for {ticker}: {exc}")
        else:
            if use_gpt4o:
                try:
                    gpt4o_result = _run_gpt4o()
                except Exception as exc:
                    logger.error(f"GPT-4o moderator failed for {ticker}: {exc}")
            if use_gemini:
                try:
                    gemini_result = _run_gemini()
                except Exception as exc:
                    logger.error(f"Gemini moderator failed for {ticker}: {exc}")

        # Multi-turn debate: let the two moderators read and rebut each other's
        # opening arguments before their final verdicts (kill switch: debate_enabled,
        # debate_rounds). Only meaningful when both moderators produced an opening.
        debate_rounds_run = 1
        gpt_verdict_changed: bool | None = None
        gemini_verdict_changed: bool | None = None
        if (
            self.settings.debate_enabled
            and self.settings.debate_rounds >= 2
            and gpt4o_result is not None
            and gemini_result is not None
        ):
            opening_gpt_verdict = gpt4o_result.get("verdict")
            opening_gemini_verdict = gemini_result.get("verdict")
            gpt4o_result, gemini_result = self._run_debate_rounds(
                trade_proposal=trade_proposal,
                portfolio_context=portfolio_context,
                market_context=market_context,
                cycle_id=cycle_id,
                research_executor=research_executor,
                gpt4o_result=gpt4o_result,
                gemini_result=gemini_result,
            )
            debate_rounds_run = self.settings.debate_rounds
            gpt_verdict_changed = bool(gpt4o_result.get("verdict") != opening_gpt_verdict)
            gemini_verdict_changed = bool(gemini_result.get("verdict") != opening_gemini_verdict)

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
            debate_rounds=debate_rounds_run,
            gpt_verdict_changed=gpt_verdict_changed,
            gemini_verdict_changed=gemini_verdict_changed,
        )

        # Log to database
        self._log_moderation(result, cycle_id)

        return result

    def _run_debate_rounds(
        self,
        *,
        trade_proposal: dict[str, Any],
        portfolio_context: str,
        market_context: dict[str, Any],
        cycle_id: str,
        research_executor: Any,
        gpt4o_result: dict[str, Any],
        gemini_result: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run rebuttal rounds where each moderator responds to the other's argument.

        Each round is simultaneous: both moderators see the other's *previous*
        argument and re-issue a verdict. A failed rebuttal keeps the prior verdict,
        so debate never makes the committee less available than the opening round.
        """
        anonymize = self.settings.debate_anonymize
        rebuttal_rounds = self.settings.debate_rounds - 1

        for _ in range(rebuttal_rounds):
            gpt_peer = _format_peer_argument(
                gemini_result, anonymize=anonymize, fallback_label="The Gemini risk assessor"
            )
            gem_peer = _format_peer_argument(
                gpt4o_result, anonymize=anonymize, fallback_label="The GPT-4o skeptic"
            )

            def _rebut_gpt4o() -> dict[str, Any] | None:
                res = openai_mod.review_trade(
                    trade_proposal, portfolio_context, market_context, cycle_id,
                    research_executor=research_executor if self.settings.skeptic_research_enabled else None,
                    peer_argument=gpt_peer,
                )
                return res if res.get("available", False) else None

            def _rebut_gemini() -> dict[str, Any] | None:
                res = gemini_mod.review_trade(
                    trade_proposal, portfolio_context, market_context, cycle_id,
                    research_executor=research_executor if self.settings.risk_research_enabled else None,
                    peer_argument=gem_peer,
                )
                return res if res.get("available", False) else None

            new_gpt: dict[str, Any] | None = None
            new_gem: dict[str, Any] | None = None

            if self.settings.parallel_moderation_enabled:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=2) as executor:
                    gpt_future = executor.submit(_rebut_gpt4o)
                    gem_future = executor.submit(_rebut_gemini)
                    try:
                        new_gpt = gpt_future.result()
                    except Exception as exc:
                        logger.error(f"GPT-4o rebuttal failed for {trade_proposal.get('ticker')}: {exc}")
                    try:
                        new_gem = gem_future.result()
                    except Exception as exc:
                        logger.error(f"Gemini rebuttal failed for {trade_proposal.get('ticker')}: {exc}")
            else:
                try:
                    new_gpt = _rebut_gpt4o()
                except Exception as exc:
                    logger.error(f"GPT-4o rebuttal failed for {trade_proposal.get('ticker')}: {exc}")
                try:
                    new_gem = _rebut_gemini()
                except Exception as exc:
                    logger.error(f"Gemini rebuttal failed for {trade_proposal.get('ticker')}: {exc}")

            # Keep prior verdict if a rebuttal failed (debate is never worse than opening).
            if new_gpt is not None:
                gpt4o_result = new_gpt
            if new_gem is not None:
                gemini_result = new_gem

        return gpt4o_result, gemini_result

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
        strategy_hash = get_strategy_prompt_hash(self.settings.strategy_model)
        skeptic_hash = openai_mod.get_skeptic_prompt_hash(self.settings.moderator_1_model)
        risk_hash = gemini_mod.get_risk_assessor_prompt_hash(self.settings.moderator_2_model)
        session = get_session()
        try:
            session.add(ModerationLog(
                timestamp=datetime.now(timezone.utc),
                cycle_id=cycle_id,
                ticker=result.ticker,
                moderator="strategy",
                verdict=result.strategy_verdict,
                reasoning="Primary strategy proposal",
                consensus=result.consensus,
                prompt_hash=strategy_hash,
                debate_rounds=result.debate_rounds,
            ))

            if result.gpt4o_verdict:
                gpt = result.gpt4o_verdict
                session.add(ModerationLog(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=result.ticker,
                    moderator="gpt-4o",
                    verdict=gpt.get("verdict", "SKIP"),
                    reasoning=gpt.get("reasoning"),
                    consensus=result.consensus,
                    confidence_score=_safe_int_score(gpt.get("confidence_score")),
                    modifications_json=_audit_json(gpt, include_high_risk=False),
                    input_tokens=_safe_int_score(gpt.get("input_tokens")),
                    output_tokens=_safe_int_score(gpt.get("output_tokens")),
                    cost_gbp=_safe_float_cost(gpt.get("cost_gbp")),
                    prompt_hash=skeptic_hash,
                    debate_rounds=result.debate_rounds,
                    verdict_changed_in_debate=result.gpt_verdict_changed,
                ))

            if result.gemini_verdict:
                gem = result.gemini_verdict
                session.add(ModerationLog(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=result.ticker,
                    moderator=gem.get("moderator", "gemini"),
                    verdict=gem.get("verdict", "SKIP"),
                    reasoning=gem.get("assessment"),
                    consensus=result.consensus,
                    growth_score=_safe_int_score(gem.get("growth_score")),
                    risk_score=_safe_int_score(gem.get("risk_score")),
                    confidence_score=_safe_int_score(gem.get("confidence_score")),
                    modifications_json=_audit_json(gem, include_high_risk=True),
                    input_tokens=_safe_int_score(gem.get("input_tokens")),
                    output_tokens=_safe_int_score(gem.get("output_tokens")),
                    cost_gbp=_safe_float_cost(gem.get("cost_gbp")),
                    prompt_hash=risk_hash,
                    debate_rounds=result.debate_rounds,
                    verdict_changed_in_debate=result.gemini_verdict_changed,
                ))

            session.commit()
        except Exception as e:
            logger.error(f"Failed to log moderation: {e}")
            session.rollback()
        finally:
            session.close()


def _safe_int_score(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float_cost(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _audit_json(verdict: dict[str, Any], *, include_high_risk: bool) -> str | None:
    payload: dict[str, Any] = {}
    mods = verdict.get("modifications")
    if isinstance(mods, dict) and mods:
        payload["modifications"] = mods
    flags = verdict.get("risk_flags")
    if isinstance(flags, list) and flags:
        payload["risk_flags"] = flags
    if include_high_risk and verdict.get("high_risk_flag") is not None:
        payload["high_risk_flag"] = bool(verdict.get("high_risk_flag"))
    return json.dumps(payload) if payload else None
