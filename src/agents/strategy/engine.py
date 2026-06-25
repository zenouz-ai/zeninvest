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
from src.utils.anthropic_cache import build_cached_system_message
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, budget_guard, check_budget, estimate_cost
from src.utils.logger import get_logger

logger = get_logger("strategy_engine")

RESEARCH_GUIDANCE = """

## RESEARCH TOOLS (use sparingly — 1–2 high-value searches per ticker)
You have web_search, news_search, sector_search, sec_search, and macro_search. Use them to verify thesis before proposing BUY.
When done researching, output your decisions as JSON in the schema below. Do not use tools after starting the JSON output."""

# Anthropic structured outputs: minimal schema only (tiered BUY fields stay prompt-driven).
# Full tiered schema exceeds Anthropic complexity limits; default slim_output_schema_enabled=false.
_STRATEGY_DECISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "action": {"type": "string"},
        "conviction": {"type": "number"},
        "reasoning": {"type": "string"},
        "exit_trigger_type": {"type": "string"},
    },
    "required": ["ticker", "action"],
    "additionalProperties": False,
}

STRATEGY_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "market_assessment": {"type": "string"},
        "decisions": {"type": "array", "items": _STRATEGY_DECISION_JSON_SCHEMA},
        "portfolio_commentary": {"type": "string"},
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


class StrategyEngine:
    """Combines sub-strategies and uses Claude for final synthesis."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: anthropic.Anthropic | None = None
        self._persist_decisions = True

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

    def _format_momentum_proposals(
        self,
        signals: list[MomentumSignal],
        ticker_filter: set[str] | None = None,
    ) -> str:
        """Format momentum signals for the prompt using the configured candidate cap."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for rank, s in enumerate(sorted_sigs[:self.settings.max_candidates]):
            if ticker_filter is not None and s.ticker not in ticker_filter:
                continue
            lines.append(self._format_signal_line(s.ticker, s.action, s.score, s.reasoning, rank))
        return "\n".join(lines) if lines else "No momentum signals"

    def _format_mean_reversion_proposals(
        self,
        signals: list[MeanReversionSignal],
        ticker_filter: set[str] | None = None,
    ) -> str:
        """Format mean reversion signals for the prompt using the configured candidate cap."""
        sorted_sigs = sorted(signals, key=lambda s: s.score, reverse=True)
        lines = []
        for rank, s in enumerate(sorted_sigs[:self.settings.max_candidates]):
            if ticker_filter is not None and s.ticker not in ticker_filter:
                continue
            lines.append(self._format_signal_line(s.ticker, s.action, s.score, s.reasoning, rank))
        return "\n".join(lines) if lines else "No mean reversion signals"

    def _format_factor_proposals(
        self,
        scores: list[FactorScore],
        ticker_filter: set[str] | None = None,
    ) -> str:
        """Format factor scores for the prompt using the configured candidate cap."""
        lines = []
        for rank, s in enumerate(scores[:self.settings.max_candidates]):
            if ticker_filter is not None and s.ticker not in ticker_filter:
                continue
            line = (
                f"- {s.ticker}: composite={s.composite_score:.0f} "
                f"(V={s.value_score:.0f} Q={s.quality_score:.0f} M={s.momentum_score:.0f})"
            )
            if rank < self.settings.strategy_sub_strategy_full_reasoning_top_n:
                if s.composite_score >= self.settings.strategy_sub_strategy_compress_score_below:
                    line += f" — {s.reasoning}"
            lines.append(line)
        return "\n".join(lines) if lines else "No factor rankings available"

    def _format_signal_line(
        self,
        ticker: str,
        action: str,
        score: float,
        reasoning: str,
        rank_index: int,
    ) -> str:
        top_n = self.settings.strategy_sub_strategy_full_reasoning_top_n
        compress_below = self.settings.strategy_sub_strategy_compress_score_below
        if rank_index >= top_n or score < compress_below:
            return f"- {ticker}: {action} (score: {score:.0f})"
        return f"- {ticker}: {action} (score: {score:.0f}) — {reasoning}"

    def _canonical_ranked_tickers(
        self,
        sub_strategy_results: dict[str, Any],
        *,
        limit: int | None = None,
        ticker_filter: set[str] | None = None,
    ) -> list[str]:
        """Score-ranked ticker list aligned across prompt sections."""
        mom = {s.ticker: s.score for s in sub_strategy_results["momentum"]}
        mr = {s.ticker: s.score for s in sub_strategy_results["mean_reversion"]}
        fac = {s.ticker: s.composite_score for s in sub_strategy_results.get("factor", [])}
        universe = set(mom) | set(mr) | set(fac)
        if ticker_filter is not None:
            universe &= ticker_filter
        scored = [(t, max(mom.get(t, 0.0), mr.get(t, 0.0), fac.get(t, 0.0))) for t in universe]
        ranked = [t for t, _ in sorted(scored, key=lambda item: item[1], reverse=True)]
        if limit is not None:
            return ranked[:limit]
        return ranked

    @staticmethod
    def _estimate_max_tokens(n_tickers: int) -> int:
        """Dynamic output budget: ~120 tokens per decision plus header."""
        return min(8192, max(1024, 120 * n_tickers + 512))

    @staticmethod
    def _extract_json_text(content: str) -> str:
        if "```json" in content:
            return content.split("```json")[1].split("```")[0]
        if "```" in content:
            return content.split("```")[1].split("```")[0]
        return content

    @staticmethod
    def _response_text(response: Any) -> str:
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]
        return "".join(b.text for b in text_blocks)

    def _finalize_result(
        self,
        result: dict[str, Any],
        expected_tickers: list[str],
        cycle_id: str,
        raw_json: str,
    ) -> dict[str, Any]:
        result = self._validate_decisions(result)
        result = self._fill_missing_hold_decisions(result, expected_tickers)
        result = self._validate_decisions(result)
        if self._persist_decisions:
            self._log_decisions(result, cycle_id, raw_json)
        return result

    @staticmethod
    def _merge_batch_results(
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> dict[str, Any]:
        decisions = list(left.get("decisions", [])) + list(right.get("decisions", []))
        market_assessment = left.get("market_assessment") or right.get("market_assessment") or ""
        portfolio_commentary = " | ".join(
            part for part in [
                str(left.get("portfolio_commentary", "")).strip(),
                str(right.get("portfolio_commentary", "")).strip(),
            ] if part
        )
        merged: dict[str, Any] = {
            "market_assessment": market_assessment,
            "decisions": decisions,
            "portfolio_commentary": portfolio_commentary,
        }
        if left.get("batch_degraded"):
            merged["batch_degraded"] = True
        if right.get("batch_degraded"):
            merged["batch_degraded"] = True
        return merged

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
        position_tickers: list[str] | None = None,
        candidate_tickers: list[str] | None = None,
        cached_prompt_prefix: str = "",
        persist_decisions: bool = True,
    ) -> dict[str, Any]:
        """Send strategy data to Claude for final synthesis."""
        if not check_budget(Provider.ANTHROPIC.value):
            logger.warning("Anthropic budget exceeded, skipping synthesis")
            return {"error": "budget_exceeded", "decisions": []}

        self._persist_decisions = persist_decisions
        try:
            if (
                self.settings.strategy_batched_synthesis_enabled
                and position_tickers is not None
                and candidate_tickers is not None
            ):
                return self.synthesize_with_claude_batched(
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
                    position_tickers=position_tickers,
                    candidate_tickers=candidate_tickers,
                    cached_prompt_prefix=cached_prompt_prefix,
                )

            all_tickers = self._canonical_ranked_tickers(
                sub_strategy_results,
                limit=self.settings.max_candidates,
            )
            return self._run_synthesis_for_tickers(
                tickers=all_tickers,
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
                batch_focus="Full universe review",
                purpose="strategy",
                use_tools=(
                    self.settings.research_enabled
                    and self.settings.strategy_research_enabled
                ),
                cached_prompt_prefix=cached_prompt_prefix,
            )
        finally:
            self._persist_decisions = True

    def synthesize_with_claude_batched(
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
        position_tickers: list[str],
        candidate_tickers: list[str],
        uov_swap_context: str = "",
        research_executor: "ResearchExecutor | None" = None,
        position_pnl: str = "",
        strategy_performance: str = "",
        cached_prompt_prefix: str = "",
    ) -> dict[str, Any]:
        """Two-batch synthesis: open positions then screened candidates."""
        position_set = {t for t in position_tickers if t}
        candidate_set = {t for t in candidate_tickers if t}

        positions_result = self._run_synthesis_for_tickers(
            tickers=self._canonical_ranked_tickers(
                sub_strategy_results,
                ticker_filter=position_set,
            ),
            sub_strategy_results=sub_strategy_results,
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            analyst_data=analyst_data,
            news_sentiment=news_sentiment,
            macro_context=macro_context,
            company_profiles="Held positions — see portfolio and P&L sections.",
            entry_quality_guards=entry_quality_guards,
            system_state=system_state,
            vix=vix,
            cash_pct=cash_pct,
            num_positions=num_positions,
            cycle_id=cycle_id,
            uov_swap_context=uov_swap_context,
            research_executor=None,
            position_pnl=position_pnl,
            strategy_performance=strategy_performance,
            batch_focus="Open positions — exit/hold/trim review only",
            purpose="strategy_positions",
            use_tools=False,
            cached_prompt_prefix=cached_prompt_prefix,
        )
        if positions_result.get("error") and not positions_result.get("decisions"):
            positions_result["batch"] = "positions"
            return positions_result

        skip_candidates = system_state == "CAUTIOUS"
        candidates_result: dict[str, Any] = {"decisions": [], "market_assessment": ""}
        if candidate_set and not skip_candidates:
            use_candidate_tools = (
                self.settings.research_enabled
                and self.settings.strategy_research_enabled
                and self.settings.strategy_candidate_research_enabled
            )
            candidates_result = self._run_synthesis_for_tickers(
                tickers=self._canonical_ranked_tickers(
                    sub_strategy_results,
                    ticker_filter=candidate_set,
                ),
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
                research_executor=research_executor if use_candidate_tools else None,
                position_pnl=position_pnl,
                strategy_performance=strategy_performance,
                batch_focus="New screened candidates — entry/BUY/QUEUED focus",
                purpose="strategy_candidates",
                use_tools=use_candidate_tools,
                cached_prompt_prefix=cached_prompt_prefix,
            )
            if candidates_result.get("error") and not candidates_result.get("decisions"):
                candidates_result["batch_degraded"] = True
                stub_tickers = self._canonical_ranked_tickers(
                    sub_strategy_results,
                    ticker_filter=candidate_set,
                )
                candidates_result = self._fill_missing_hold_decisions(
                    {"decisions": [], "market_assessment": ""},
                    stub_tickers,
                )
                if self._persist_decisions:
                    self._log_decisions(candidates_result, cycle_id, "")

        merged = self._merge_batch_results(positions_result, candidates_result)
        if candidates_result.get("batch_degraded"):
            merged["batch_degraded"] = True
            merged["candidate_batch_error"] = candidates_result.get("error")
        merged["market_assessment"] = (
            candidates_result.get("market_assessment")
            or positions_result.get("market_assessment")
            or ""
        )
        return merged

    def _run_synthesis_for_tickers(
        self,
        *,
        tickers: list[str],
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
        research_executor: "ResearchExecutor | None",
        position_pnl: str,
        strategy_performance: str,
        batch_focus: str,
        purpose: str,
        use_tools: bool,
        cached_prompt_prefix: str,
    ) -> dict[str, Any]:
        if not tickers:
            return {"decisions": [], "market_assessment": ""}

        result = self._run_synthesis_once(
            tickers=tickers,
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
            batch_focus=batch_focus,
            purpose=purpose,
            use_tools=use_tools,
            cached_prompt_prefix=cached_prompt_prefix,
        )
        if result.get("error") == "json_truncated" and len(tickers) > 1:
            mid = len(tickers) // 2
            left = self._run_synthesis_for_tickers(
                tickers=tickers[:mid],
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
                batch_focus=batch_focus,
                purpose=purpose,
                use_tools=use_tools,
                cached_prompt_prefix=cached_prompt_prefix,
            )
            right = self._run_synthesis_for_tickers(
                tickers=tickers[mid:],
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
                batch_focus=batch_focus,
                purpose=purpose,
                use_tools=use_tools,
                cached_prompt_prefix=cached_prompt_prefix,
            )
            if left.get("error") and not left.get("decisions"):
                return left
            if right.get("error") and not right.get("decisions"):
                return right
            return self._merge_batch_results(left, right)
        return result

    def _run_synthesis_once(
        self,
        *,
        tickers: list[str],
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
        research_executor: "ResearchExecutor | None",
        position_pnl: str,
        strategy_performance: str,
        batch_focus: str,
        purpose: str,
        use_tools: bool,
        cached_prompt_prefix: str,
    ) -> dict[str, Any]:
        ticker_filter = set(tickers)
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
                tickers=tickers,
                ticker_filter=ticker_filter,
                batch_focus=batch_focus,
                purpose=purpose,
                cached_prompt_prefix=cached_prompt_prefix,
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
            tickers=tickers,
            ticker_filter=ticker_filter,
            batch_focus=batch_focus,
            purpose=purpose,
            cached_prompt_prefix=cached_prompt_prefix,
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
        tickers: list[str] | None = None,
        ticker_filter: set[str] | None = None,
        batch_focus: str = "Full universe review",
        purpose: str = "strategy",
        cached_prompt_prefix: str = "",
    ) -> dict[str, Any]:
        """Original single-turn synthesis without tools."""
        max_pos_pct = self.settings.max_position_pct
        if system_state == "CAUTIOUS":
            max_pos_pct = 8.0

        expected_tickers = tickers or self._canonical_ranked_tickers(
            sub_strategy_results,
            limit=self.settings.max_candidates,
            ticker_filter=ticker_filter,
        )
        tickers_list = ", ".join(expected_tickers)

        prompt = build_strategy_prompt(
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            momentum_proposals=self._format_momentum_proposals(
                sub_strategy_results["momentum"], ticker_filter=ticker_filter,
            ),
            mean_reversion_proposals=self._format_mean_reversion_proposals(
                sub_strategy_results["mean_reversion"], ticker_filter=ticker_filter,
            ),
            factor_proposals=self._format_factor_proposals(
                sub_strategy_results.get("top_factor", []), ticker_filter=ticker_filter,
            ),
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
            batch_focus=batch_focus,
        )

        max_tokens = self._estimate_max_tokens(len(expected_tickers))
        system_message = build_cached_system_message(
            STRATEGY_SYSTEM_PROMPT,
            cached_prompt_prefix,
            caching_enabled=self.settings.strategy_prompt_caching_enabled,
        )

        try:
            with budget_guard(
                Provider.ANTHROPIC.value,
                estimate_cost(Provider.ANTHROPIC.value, prompt + STRATEGY_SYSTEM_PROMPT, max_tokens),
                model=self.settings.strategy_model,
                purpose=purpose,
                cycle_id=cycle_id,
            ) as guard:
                if not guard.approved:
                    logger.warning("Anthropic budget exceeded, skipping synthesis")
                    return {"error": "budget_exceeded", "decisions": []}
                create_kwargs: dict[str, Any] = {
                    "model": self.settings.strategy_model,
                    "max_tokens": max_tokens,
                    "system": system_message,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if self.settings.strategy_slim_output_schema_enabled:
                    create_kwargs["output_config"] = {
                        "format": {
                            "type": "json_schema",
                            "schema": STRATEGY_OUTPUT_JSON_SCHEMA,
                        },
                    }
                response = self.client.messages.create(**create_kwargs)
                guard.settle(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    model=self.settings.strategy_model,
                )

            return self._parse_response_payload(
                response=response,
                messages=[{"role": "user", "content": prompt}],
                expected_tickers=expected_tickers,
                cycle_id=cycle_id,
                purpose=purpose,
                max_tokens=max_tokens,
                system_message=system_message,
                use_tools=False,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return {"error": "json_parse_error", "decisions": []}
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
        tickers: list[str] | None = None,
        ticker_filter: set[str] | None = None,
        batch_focus: str = "Full universe review",
        purpose: str = "strategy",
        cached_prompt_prefix: str = "",
    ) -> dict[str, Any]:
        """Tool-use loop: Claude can call research tools, then output decisions JSON."""
        max_pos_pct = self.settings.max_position_pct
        if system_state == "CAUTIOUS":
            max_pos_pct = 8.0

        expected_tickers = tickers or self._canonical_ranked_tickers(
            sub_strategy_results,
            limit=self.settings.max_candidates,
            ticker_filter=ticker_filter,
        )
        tickers_list = ", ".join(expected_tickers)
        max_tokens = self._estimate_max_tokens(len(expected_tickers))

        prompt = build_strategy_prompt(
            portfolio_state=portfolio_state,
            market_regime=market_regime,
            momentum_proposals=self._format_momentum_proposals(
                sub_strategy_results["momentum"], ticker_filter=ticker_filter,
            ),
            mean_reversion_proposals=self._format_mean_reversion_proposals(
                sub_strategy_results["mean_reversion"], ticker_filter=ticker_filter,
            ),
            factor_proposals=self._format_factor_proposals(
                sub_strategy_results.get("top_factor", []), ticker_filter=ticker_filter,
            ),
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
            batch_focus=batch_focus,
        )
        prompt = prompt + RESEARCH_GUIDANCE

        executor = research_executor or ResearchExecutor(cycle_id=cycle_id)
        tools = get_research_tool_definitions()
        messages: list[dict] = [{"role": "user", "content": prompt}]
        max_iterations = 8
        timeout_sec = 120
        start = time.perf_counter()
        system_message = build_cached_system_message(
            STRATEGY_SYSTEM_PROMPT,
            cached_prompt_prefix,
            caching_enabled=self.settings.strategy_prompt_caching_enabled,
        )

        for iteration in range(max_iterations):
            if time.perf_counter() - start > timeout_sec:
                logger.warning("Strategy tool-use timeout")
                return {"error": "research_timeout", "decisions": []}

            with budget_guard(
                Provider.ANTHROPIC.value,
                estimate_cost(Provider.ANTHROPIC.value, prompt + STRATEGY_SYSTEM_PROMPT, max_tokens),
                model=self.settings.strategy_model,
                purpose=purpose,
                cycle_id=cycle_id,
            ) as guard:
                if not guard.approved:
                    logger.warning("Anthropic budget exceeded mid tool-use loop")
                    return {"error": "budget_exceeded", "decisions": []}
                try:
                    response = self.client.messages.create(
                        model=self.settings.strategy_model,
                        max_tokens=max_tokens,
                        tools=tools,
                        system=system_message,
                        messages=messages,
                    )
                except Exception as e:
                    logger.error(f"Claude tool-use request failed: {e}")
                    return {"error": str(e), "decisions": []}

                guard.settle(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    model=self.settings.strategy_model,
                )

            tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]

            if text_blocks and not tool_use_blocks:
                parsed = self._parse_response_payload(
                    response=response,
                    messages=messages,
                    expected_tickers=expected_tickers,
                    cycle_id=cycle_id,
                    purpose=purpose,
                    max_tokens=max_tokens,
                    system_message=system_message,
                    use_tools=True,
                )
                return parsed

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

    def _parse_response_payload(
        self,
        *,
        response: Any,
        messages: list[dict],
        expected_tickers: list[str],
        cycle_id: str,
        purpose: str,
        max_tokens: int,
        system_message: Any,
        use_tools: bool,
    ) -> dict[str, Any]:
        content = self._extract_json_text(self._response_text(response))
        stop_reason = response.stop_reason

        if stop_reason == "max_tokens":
            logger.warning("Claude response truncated at max_tokens=%s; attempting continuation", max_tokens)
            continued = self._try_continue_truncated_response(
                partial_content=content,
                messages=messages,
                response=response,
                expected_tickers=expected_tickers,
                cycle_id=cycle_id,
                purpose=purpose,
                max_tokens=max_tokens,
                system_message=system_message,
                use_tools=use_tools,
            )
            if continued is not None:
                return continued

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            if stop_reason == "max_tokens":
                result = self._repair_truncated_json(content)
                if result is None:
                    return {
                        "error": "json_truncated",
                        "decisions": [],
                        "stop_reason": stop_reason,
                    }
            else:
                return {"error": "json_parse_error", "decisions": [], "raw": content}

        return self._finalize_result(result, expected_tickers, cycle_id, content)

    def _try_continue_truncated_response(
        self,
        *,
        partial_content: str,
        messages: list[dict],
        response: Any,
        expected_tickers: list[str],
        cycle_id: str,
        purpose: str,
        max_tokens: int,
        system_message: Any,
        use_tools: bool,
    ) -> dict[str, Any] | None:
        """Resume generation by appending the partial assistant JSON."""
        continuation_messages = list(messages)
        continuation_messages.append({"role": "assistant", "content": response.content})
        continuation_messages.append({
            "role": "user",
            "content": "Continue the JSON object exactly where you left off. No preamble.",
        })
        try:
            with budget_guard(
                Provider.ANTHROPIC.value,
                estimate_cost(Provider.ANTHROPIC.value, partial_content, max_tokens),
                model=self.settings.strategy_model,
                purpose=purpose,
                cycle_id=cycle_id,
            ) as guard:
                if not guard.approved:
                    return None
                create_kwargs: dict[str, Any] = {
                    "model": self.settings.strategy_model,
                    "max_tokens": max_tokens,
                    "system": system_message,
                    "messages": continuation_messages,
                }
                if use_tools:
                    create_kwargs["tools"] = get_research_tool_definitions()
                cont_response = self.client.messages.create(**create_kwargs)
                guard.settle(
                    cont_response.usage.input_tokens,
                    cont_response.usage.output_tokens,
                    model=self.settings.strategy_model,
                )
            combined = partial_content + self._response_text(cont_response)
            combined_clean = self._extract_json_text(combined)
            try:
                result = json.loads(combined_clean)
            except json.JSONDecodeError:
                result = self._repair_truncated_json(combined_clean)
                if result is None:
                    return None
            return self._finalize_result(result, expected_tickers, cycle_id, combined_clean)
        except Exception as exc:
            logger.warning("Continuation after truncation failed: %s", exc)
            return None

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
