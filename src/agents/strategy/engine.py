"""Strategy engine — orchestrates sub-strategies and Claude synthesis."""

import json
import time
from datetime import datetime, timezone
from typing import Any

import anthropic

from src.agents.research import ResearchExecutor, get_research_tool_definitions
from src.agents.strategy.factor import FactorScore, calculate_factor_score, rank_by_factor
from src.agents.strategy.mean_reversion import MeanReversionSignal, evaluate_mean_reversion
from src.agents.strategy.momentum import MomentumSignal, evaluate_momentum
from src.agents.strategy.prompts import STRATEGY_SYSTEM_PROMPT, build_strategy_prompt, get_strategy_prompt_hash
from src.data.database import get_session
from src.data.models import StrategyDecision
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("strategy_engine")

RESEARCH_GUIDANCE = """

## RESEARCH TOOLS (use sparingly — 1–2 high-value searches per ticker)
You have web_search, news_search, sector_search, sec_search, and macro_search. Use them to verify thesis before proposing BUY.
When done researching, output your decisions as JSON in the schema below. Do not use tools after starting the JSON output."""


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

        # Rank factor ideas using the same candidate cap that drives the screening universe.
        top_factor = rank_by_factor(factor_scores, top_n=self.settings.max_candidates)

        return {
            "momentum": momentum_signals,
            "mean_reversion": mean_reversion_signals,
            "factor": factor_scores,
            "top_factor": top_factor,
        }

    def _format_momentum_proposals(self, signals: list[MomentumSignal]) -> str:
        """Format momentum signals for the prompt using the configured candidate cap."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for s in sorted_sigs[:self.settings.max_candidates]:
            lines.append(f"- {s.ticker}: {s.action} (score: {s.score:.0f}) — {s.reasoning}")
        return "\n".join(lines) if lines else "No momentum signals"

    def _format_mean_reversion_proposals(self, signals: list[MeanReversionSignal]) -> str:
        """Format mean reversion signals for the prompt using the configured candidate cap."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for s in sorted_sigs[:self.settings.max_candidates]:
            lines.append(f"- {s.ticker}: {s.action} (score: {s.score:.0f}) — {s.reasoning}")
        return "\n".join(lines) if lines else "No mean reversion signals"

    def _format_factor_proposals(self, scores: list[FactorScore]) -> str:
        """Format factor scores for the prompt using the configured candidate cap."""
        lines = []
        for s in scores[:self.settings.max_candidates]:
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
        macro_context: str,
        company_profiles: str,
        entry_quality_guards: str,
        system_state: str,
        vix: float | None,
        cash_pct: float,
        num_positions: int,
        cycle_id: str,
        uov_swap_context: str = "",
        research_executor: "ResearchExecutor | None" = None,
        position_pnl: str = "",
        strategy_performance: str = "",
    ) -> dict[str, Any]:
        """Send strategy data to Claude for final synthesis."""
        if not check_budget(Provider.ANTHROPIC.value):
            logger.warning("Anthropic budget exceeded, skipping synthesis")
            return {"error": "budget_exceeded", "decisions": []}

        use_tools = (
            self.settings.research_enabled
            and self.settings.strategy_research_enabled
        )
        if use_tools:
            return self._synthesize_with_tools(
                sub_strategy_results=sub_strategy_results,
                portfolio_state=portfolio_state,
                market_regime=market_regime,
                analyst_data=analyst_data,
                news_sentiment=news_sentiment,
                macro_context=macro_context,
                company_profiles=company_profiles,
                entry_quality_guards=entry_quality_guards,
                system_state=system_state,
                vix=vix,
                cash_pct=cash_pct,
                num_positions=num_positions,
                cycle_id=cycle_id,
                uov_swap_context=uov_swap_context,
                research_executor=research_executor,
                position_pnl=position_pnl,
                strategy_performance=strategy_performance,
            )

        return self._synthesize_single_turn(
            sub_strategy_results=sub_strategy_results,
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            analyst_data=analyst_data,
            news_sentiment=news_sentiment,
            macro_context=macro_context,
            company_profiles=company_profiles,
            entry_quality_guards=entry_quality_guards,
            system_state=system_state,
            vix=vix,
            cash_pct=cash_pct,
            num_positions=num_positions,
            cycle_id=cycle_id,
            uov_swap_context=uov_swap_context,
            position_pnl=position_pnl,
            strategy_performance=strategy_performance,
        )

    def _synthesize_single_turn(
        self,
        sub_strategy_results: dict[str, Any],
        portfolio_state: str,
        market_regime: str,
        analyst_data: str,
        news_sentiment: str,
        macro_context: str,
        company_profiles: str,
        entry_quality_guards: str,
        system_state: str,
        vix: float | None,
        cash_pct: float,
        num_positions: int,
        cycle_id: str,
        uov_swap_context: str,
        position_pnl: str = "",
        strategy_performance: str = "",
    ) -> dict[str, Any]:
        """Original single-turn synthesis without tools."""
        max_pos_pct = self.settings.max_position_pct
        if system_state == "CAUTIOUS":
            max_pos_pct = 8.0

        all_tickers = [s.ticker for s in sub_strategy_results["momentum"]]
        tickers_list = ", ".join(all_tickers[:self.settings.max_candidates])

        prompt = build_strategy_prompt(
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            momentum_proposals=self._format_momentum_proposals(sub_strategy_results["momentum"]),
            mean_reversion_proposals=self._format_mean_reversion_proposals(sub_strategy_results["mean_reversion"]),
            factor_proposals=self._format_factor_proposals(sub_strategy_results.get("top_factor", [])),
            analyst_data=analyst_data,
            news_sentiment=news_sentiment,
            macro_context=macro_context,
            company_profiles=company_profiles,
            entry_quality_guards=entry_quality_guards,
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
            position_pnl=position_pnl,
            strategy_performance=strategy_performance,
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

            # Validate and log decisions (audit fix H-5)
            result = self._validate_decisions(result)
            result = self._fill_missing_hold_decisions(result, all_tickers)
            result = self._validate_decisions(result)
            self._log_decisions(result, cycle_id, content)

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return {"error": "json_parse_error", "decisions": [], "raw": content}
        except Exception as e:
            logger.error(f"Claude synthesis failed: {e}")
            return {"error": str(e), "decisions": []}

    def _synthesize_with_tools(
        self,
        sub_strategy_results: dict[str, Any],
        portfolio_state: str,
        market_regime: str,
        analyst_data: str,
        news_sentiment: str,
        macro_context: str,
        company_profiles: str,
        entry_quality_guards: str,
        system_state: str,
        vix: float | None,
        cash_pct: float,
        num_positions: int,
        cycle_id: str,
        uov_swap_context: str,
        research_executor: "ResearchExecutor | None" = None,
        position_pnl: str = "",
        strategy_performance: str = "",
    ) -> dict[str, Any]:
        """Tool-use loop: Claude can call research tools, then output decisions JSON."""
        max_pos_pct = self.settings.max_position_pct
        if system_state == "CAUTIOUS":
            max_pos_pct = 8.0

        all_tickers = [s.ticker for s in sub_strategy_results["momentum"]]
        tickers_list = ", ".join(all_tickers[:self.settings.max_candidates])

        prompt = build_strategy_prompt(
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            momentum_proposals=self._format_momentum_proposals(sub_strategy_results["momentum"]),
            mean_reversion_proposals=self._format_mean_reversion_proposals(sub_strategy_results["mean_reversion"]),
            factor_proposals=self._format_factor_proposals(sub_strategy_results.get("top_factor", [])),
            analyst_data=analyst_data,
            news_sentiment=news_sentiment,
            macro_context=macro_context,
            company_profiles=company_profiles,
            entry_quality_guards=entry_quality_guards,
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
            position_pnl=position_pnl,
            strategy_performance=strategy_performance,
        )
        prompt = prompt + RESEARCH_GUIDANCE

        executor = research_executor or ResearchExecutor(cycle_id=cycle_id)
        tools = get_research_tool_definitions()
        messages: list[dict] = [{"role": "user", "content": prompt}]
        max_iterations = 8
        timeout_sec = 120  # 2 minutes (audit fix H-3: 30s was too aggressive for tool-use)
        start = time.perf_counter()

        for iteration in range(max_iterations):
            if time.perf_counter() - start > timeout_sec:
                logger.warning("Strategy tool-use timeout")
                return {"error": "research_timeout", "decisions": []}

            try:
                response = self.client.messages.create(
                    model=self.settings.strategy_model,
                    max_tokens=16384,
                    tools=tools,
                    system=STRATEGY_SYSTEM_PROMPT,
                    messages=messages,
                )
            except Exception as e:
                logger.error(f"Claude tool-use request failed: {e}")
                return {"error": str(e), "decisions": []}

            log_cost(
                provider=Provider.ANTHROPIC.value,
                model=self.settings.strategy_model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cycle_id=cycle_id,
                purpose="strategy",
            )

            tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]

            if text_blocks and not tool_use_blocks:
                content = "".join(b.text for b in text_blocks)
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    if response.stop_reason == "max_tokens":
                        result = self._repair_truncated_json(content)
                        if result is None:
                            return {"error": "json_truncated", "decisions": []}
                    else:
                        return {"error": "json_parse_error", "decisions": [], "raw": content}
                result = self._validate_decisions(result)
                result = self._fill_missing_hold_decisions(result, all_tickers)
                result = self._validate_decisions(result)
                self._log_decisions(result, cycle_id, content)
                return result

            if not tool_use_blocks:
                return {"error": "no_final_response", "decisions": []}

            tool_results: list[dict] = []
            for block in tool_use_blocks:
                tool_id = block.id
                name = block.name
                inp = block.input if isinstance(block.input, dict) else {}
                ticker = inp.get("ticker", "general")
                num_results = inp.get("num_results", 5)

                if name == "web_search":
                    res = executor.web_search("strategy", ticker or "general", inp.get("query", ""), num_results)
                elif name == "news_search":
                    res = executor.news_search("strategy", ticker or "general", inp.get("query", ""), num_results)
                elif name == "sector_search":
                    res = executor.sector_search(
                        "strategy", ticker or "general",
                        inp.get("sector", ""), inp.get("query", ""), num_results,
                    )
                elif name == "sec_search":
                    res = executor.sec_search_tool(
                        "strategy", ticker or "general",
                        inp.get("doc_type", "10-K"), num_results or 3,
                    )
                elif name == "macro_search":
                    res = executor.macro_search("strategy", inp.get("query", ""), num_results)
                else:
                    res = [{"error": f"Unknown tool: {name}"}]

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(res)[:8000] if res else "[]",
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        logger.warning("Strategy tool-use hit max iterations without final JSON")
        return {"error": "max_tool_iterations", "decisions": []}

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

    @staticmethod
    def _validate_decisions(result: dict[str, Any]) -> dict[str, Any]:
        """Validate and filter decisions — drop any with missing required fields (audit fix H-5)."""
        valid_actions = {"BUY", "SELL", "HOLD", "REDUCE", "QUEUED"}
        valid_exit_trigger_types = {"none", "gain_realization", "hard_exit", "profit_trim"}
        validated = []
        for d in result.get("decisions", []):
            ticker = d.get("ticker", "").strip()
            action = d.get("action", "").strip().upper()
            conviction = d.get("conviction")
            if not ticker:
                logger.warning(f"Dropping decision with empty ticker: {d}")
                continue
            if action not in valid_actions:
                logger.warning(f"Dropping decision with invalid action '{action}' for {ticker}")
                continue
            if action in ("BUY", "SELL", "REDUCE") and (conviction is None or conviction == 0):
                logger.warning(f"Dropping {action} decision for {ticker}: conviction is {conviction}")
                continue
            raw_exit_trigger = str(d.get("exit_trigger_type", "") or "").strip().lower()
            if not raw_exit_trigger:
                raw_exit_trigger = "none" if action in {"BUY", "HOLD", "QUEUED"} else ""
            if raw_exit_trigger not in valid_exit_trigger_types:
                logger.warning(
                    "Dropping %s decision for %s: invalid exit_trigger_type %r",
                    action,
                    ticker,
                    d.get("exit_trigger_type"),
                )
                continue
            if action == "SELL" and raw_exit_trigger not in {"gain_realization", "hard_exit"}:
                logger.warning(
                    "Dropping SELL decision for %s: exit_trigger_type %r is not allowed",
                    ticker,
                    raw_exit_trigger,
                )
                continue
            if action == "REDUCE" and raw_exit_trigger != "profit_trim":
                logger.warning(
                    "Dropping REDUCE decision for %s: exit_trigger_type %r is not profit_trim",
                    ticker,
                    raw_exit_trigger,
                )
                continue
            if action in {"BUY", "HOLD", "QUEUED"}:
                raw_exit_trigger = "none"
            d["exit_trigger_type"] = raw_exit_trigger
            validated.append(d)
        dropped = len(result.get("decisions", [])) - len(validated)
        if dropped > 0:
            logger.warning(f"Dropped {dropped} invalid decisions after validation")
        result["decisions"] = validated
        return result

    @staticmethod
    def _fill_missing_hold_decisions(result: dict[str, Any], expected_tickers: list[str]) -> dict[str, Any]:
        """Ensure every ticker sent to strategy gets an auditable decision row."""
        decided = {d.get("ticker", "").strip() for d in result.get("decisions", []) if d.get("ticker")}
        for ticker in expected_tickers:
            if ticker in decided:
                continue
            result.setdefault("decisions", []).append(
                {
                    "ticker": ticker,
                    "action": "HOLD",
                    "conviction": 1,
                    "reasoning": (
                        "No explicit committee output for this cycle; deterministic HOLD stub "
                        "for audit coverage."
                    ),
                    "exit_trigger_type": "none",
                }
            )
        return result

    def _log_decisions(self, result: dict[str, Any], cycle_id: str, raw_json: str) -> None:
        """Log strategy decisions to database."""
        session = get_session()
        try:
            market_assessment = result.get("market_assessment", "")
            portfolio_commentary = result.get("portfolio_commentary", "")
            prompt_hash = get_strategy_prompt_hash(self.settings.strategy_model)

            for decision in result.get("decisions", []):
                session.add(StrategyDecision(
                    timestamp=datetime.now(timezone.utc),
                    cycle_id=cycle_id,
                    ticker=decision.get("ticker", ""),
                    action=decision.get("action", ""),
                    target_allocation_pct=decision.get("target_allocation_pct"),
                    risk_parity_target_allocation_pct=decision.get("risk_parity_target_allocation_pct"),
                    risk_parity_trailing_vol_pct=decision.get("risk_parity_trailing_vol_pct"),
                    risk_parity_applied=decision.get("risk_parity_applied"),
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
                    prompt_hash=prompt_hash,
                ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log strategy decisions: {e}")
            session.rollback()
        finally:
            session.close()

    def apply_risk_parity_metadata(self, cycle_id: str, decisions: list[dict[str, Any]]) -> None:
        """Persist risk-parity fields after strategy rows are initially logged."""
        session = get_session()
        try:
            by_ticker = {
                str(decision.get("ticker", "")).strip().upper(): decision
                for decision in decisions
                if decision.get("ticker")
            }
            rows = (
                session.query(StrategyDecision)
                .filter(StrategyDecision.cycle_id == cycle_id)
                .all()
            )
            for row in rows:
                decision = by_ticker.get(str(row.ticker).strip().upper())
                if decision is None:
                    continue
                row.risk_parity_target_allocation_pct = decision.get("risk_parity_target_allocation_pct")
                row.risk_parity_trailing_vol_pct = decision.get("risk_parity_trailing_vol_pct")
                row.risk_parity_applied = decision.get("risk_parity_applied")
            session.commit()
        except Exception as e:
            logger.error(f"Failed to apply risk-parity metadata: {e}")
            session.rollback()
        finally:
            session.close()
