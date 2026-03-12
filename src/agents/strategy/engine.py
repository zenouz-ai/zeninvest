"""Strategy engine — orchestrates sub-strategies and Claude synthesis."""

import json
from datetime import datetime, timezone
from typing import Any

import anthropic

from src.agents.strategy.factor import FactorScore, calculate_factor_score, rank_by_factor
from src.agents.strategy.mean_reversion import MeanReversionSignal, evaluate_mean_reversion
from src.agents.strategy.momentum import MomentumSignal, evaluate_momentum
from src.agents.strategy.prompts import STRATEGY_SYSTEM_PROMPT, build_strategy_prompt
from src.data.database import get_session
from src.data.models import StrategyDecision
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("strategy_engine")


class StrategyEngine:
    """Combines sub-strategies and uses Claude for final synthesis."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def run_sub_strategies(
        self,
        stocks_data: list[dict[str, Any]],
        existing_positions: set[str],
    ) -> dict[str, Any]:
        """Run all three sub-strategies on the stock universe.

        Args:
            stocks_data: List of dicts with keys: ticker, indicators, fundamentals, relative_strength
            existing_positions: Set of currently held tickers
        """
        momentum_signals: list[MomentumSignal] = []
        mean_reversion_signals: list[MeanReversionSignal] = []
        factor_scores: list[FactorScore] = []

        for stock in stocks_data:
            ticker = stock["ticker"]
            indicators = stock.get("indicators", {})
            fundamentals = stock.get("fundamentals", {})
            rs = stock.get("relative_strength_6m")
            is_held = ticker in existing_positions

            # Momentum
            mom_signal = evaluate_momentum(ticker, indicators, rs, current_holding=is_held)
            momentum_signals.append(mom_signal)

            # Mean Reversion
            mr_signal = evaluate_mean_reversion(
                ticker, indicators, fundamentals,
                sector_avg_pe=stock.get("sector_avg_pe"),
                current_holding=is_held,
            )
            mean_reversion_signals.append(mr_signal)

            # Factor
            six_mo_return = stock.get("six_month_return")
            factor_score = calculate_factor_score(ticker, fundamentals, indicators, rs, six_mo_return)
            factor_scores.append(factor_score)

        # Rank by factor score (top 30 for 60-90 decisions/day target)
        top_factor = rank_by_factor(factor_scores, top_n=30)

        return {
            "momentum": momentum_signals,
            "mean_reversion": mean_reversion_signals,
            "factor": factor_scores,
            "top_factor": top_factor,
        }

    def _format_momentum_proposals(self, signals: list[MomentumSignal]) -> str:
        """Format momentum signals for the prompt. Include all tickers (up to 35) for one-decision-per-ticker."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for s in sorted_sigs[:35]:
            lines.append(f"- {s.ticker}: {s.action} (score: {s.score:.0f}) — {s.reasoning}")
        return "\n".join(lines) if lines else "No momentum signals"

    def _format_mean_reversion_proposals(self, signals: list[MeanReversionSignal]) -> str:
        """Format mean reversion signals for the prompt. Include all tickers (up to 35)."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for s in sorted_sigs[:35]:
            lines.append(f"- {s.ticker}: {s.action} (score: {s.score:.0f}) — {s.reasoning}")
        return "\n".join(lines) if lines else "No mean reversion signals"

    def _format_factor_proposals(self, scores: list[FactorScore]) -> str:
        """Format factor scores for the prompt. Include top 30."""
        lines = []
        for s in scores[:30]:
            lines.append(
                f"- {s.ticker}: composite={s.composite_score:.0f} "
                f"(V={s.value_score:.0f} Q={s.quality_score:.0f} M={s.momentum_score:.0f}) — {s.reasoning}"
            )
        return "\n".join(lines) if lines else "No factor rankings available"

    def synthesize_with_claude(
        self,
        sub_strategy_results: dict[str, Any],
        portfolio_state: str,
        market_regime: str,
        analyst_data: str,
        news_sentiment: str,
        company_profiles: str,
        system_state: str,
        vix: float | None,
        cash_pct: float,
        num_positions: int,
        cycle_id: str,
        uov_swap_context: str = "",
    ) -> dict[str, Any]:
        """Send strategy data to Claude for final synthesis."""
        if not check_budget(Provider.ANTHROPIC.value):
            logger.warning("Anthropic budget exceeded, skipping synthesis")
            return {"error": "budget_exceeded", "decisions": []}

        max_pos_pct = self.settings.max_position_pct
        if system_state == "CAUTIOUS":
            max_pos_pct = 8.0

        all_tickers = [s.ticker for s in sub_strategy_results["momentum"]]
        tickers_list = ", ".join(all_tickers[:35])

        prompt = build_strategy_prompt(
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            momentum_proposals=self._format_momentum_proposals(sub_strategy_results["momentum"]),
            mean_reversion_proposals=self._format_mean_reversion_proposals(sub_strategy_results["mean_reversion"]),
            factor_proposals=self._format_factor_proposals(sub_strategy_results.get("top_factor", [])),
            analyst_data=analyst_data,
            news_sentiment=news_sentiment,
            company_profiles=company_profiles,
            tickers_to_decide=tickers_list,
            system_state=system_state,
            vix=vix,
            cash_pct=cash_pct,
            max_position_pct=max_pos_pct,
            num_positions=num_positions,
            max_positions=self.settings.max_positions,
            momentum_weight=self.settings.momentum_weight,
            mean_reversion_weight=self.settings.mean_reversion_weight,
            factor_weight=self.settings.factor_weight,
            uov_swap_context=uov_swap_context,
        )

        try:
            response = self.client.messages.create(
                model=self.settings.strategy_model,
                max_tokens=16384,  # Support 30+ decisions (one per ticker)
                system=STRATEGY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Log cost
            log_cost(
                provider=Provider.ANTHROPIC.value,
                model=self.settings.strategy_model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cycle_id=cycle_id,
                purpose="strategy",
            )

            # Check for truncation (stop_reason="end_turn" = complete, "max_tokens" = truncated)
            if response.stop_reason == "max_tokens":
                logger.warning("Claude response was truncated (hit max_tokens). Attempting partial parse.")

            # Parse response
            content = response.content[0].text
            # Try to extract JSON if wrapped in code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # If truncated, try to salvage by closing the JSON structure
                if response.stop_reason == "max_tokens":
                    result = self._repair_truncated_json(content)
                    if result is None:
                        return {"error": "json_truncated", "decisions": []}
                else:
                    raise

            # Log decisions
            self._log_decisions(result, cycle_id, content)

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return {"error": "json_parse_error", "decisions": [], "raw": content}
        except Exception as e:
            logger.error(f"Claude synthesis failed: {e}")
            return {"error": str(e), "decisions": []}

    @staticmethod
    def _repair_truncated_json(content: str) -> dict[str, Any] | None:
        """Attempt to salvage a truncated JSON response by closing open structures.

        Finds the last complete decision object in the decisions array and closes
        the JSON. Returns None if repair fails.
        """
        # Find the last complete decision object (ends with "}")
        # by looking for the last '}' that could close a decision
        last_complete = content.rfind("}")
        if last_complete == -1:
            return None

        # Try progressively shorter substrings, closing the array and outer object
        for i in range(last_complete + 1, max(last_complete - 500, 0), -1):
            candidate = content[:i]
            # Try closing with ], "portfolio_commentary": ""} variants
            for suffix in [
                '], "portfolio_commentary": "truncated"}',
                "]}",
                "}]}",
            ]:
                try:
                    result = json.loads(candidate + suffix)
                    if "decisions" in result:
                        logger.warning(
                            f"Repaired truncated JSON: {len(result['decisions'])} decisions recovered"
                        )
                        return result
                except json.JSONDecodeError:
                    continue

        return None

    def _log_decisions(self, result: dict[str, Any], cycle_id: str, raw_json: str) -> None:
        """Log strategy decisions to database."""
        session = get_session()
        try:
            market_assessment = result.get("market_assessment", "")
            portfolio_commentary = result.get("portfolio_commentary", "")

            for decision in result.get("decisions", []):
                session.add(StrategyDecision(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=decision.get("ticker", ""),
                    action=decision.get("action", ""),
                    target_allocation_pct=decision.get("target_allocation_pct"),
                    conviction=decision.get("conviction"),
                    primary_strategy=decision.get("primary_strategy"),
                    reasoning=decision.get("reasoning"),
                    growth_potential=decision.get("growth_potential"),
                    risk_level=decision.get("risk_level"),
                    catalysts_json=json.dumps(decision.get("catalysts", [])),
                    risks_json=json.dumps(decision.get("risks", [])),
                    exit_conditions=decision.get("exit_conditions"),
                    upside_target_pct=decision.get("upside_target_pct"),
                    stop_loss_pct=decision.get("stop_loss_pct"),
                    expected_holding_period=decision.get("expected_holding_period"),
                    news_sentiment_summary=decision.get("news_sentiment_summary"),
                    market_assessment=market_assessment,
                    portfolio_commentary=portfolio_commentary,
                    raw_response_json=raw_json,
                ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log strategy decisions: {e}")
            session.rollback()
        finally:
            session.close()
