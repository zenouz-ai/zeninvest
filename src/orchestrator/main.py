"""Orchestrator — main control loop for the investment agent.

Runs every 12 hours during market hours (configurable).
Sequence: Data -> Strategy -> Moderation -> Risk -> Execution -> Journal
"""

import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

import click

from src.agents.execution.order_manager import OrderManager
from src.agents.execution.stop_loss_manager import StopLossManager
from src.agents.execution.t212_client import T212Client
from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
from src.agents.market_data.brave_enrichment import (
    get_news_sentiment_fallback,
    get_news_sentiment_fallback_batch,
)
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.market_data.macro_intelligence import get_sector_headwind
from src.agents.moderation.panel import ModerationPanel
from src.agents.notifications import NotificationService
from src.agents.opportunity.optimizer import OpportunityOptimizer
from src.agents.opportunity.scorer import OpportunityScorer
from src.agents.reporting.journal import generate_trade_journal
from src.agents.reporting.performance_tracker import update_performance_metrics
from src.agents.reporting.trade_outcome_tracker import update_trade_outcomes
from src.agents.risk.risk_manager import RiskManager
from src.agents.strategy.engine import StrategyEngine
from src.data.database import get_session
from src.data.models import Base, Instrument, PerformanceMetric, PortfolioSnapshot
from src.orchestrator.state_machine import StateMachine
from src.utils.config import get_settings
from src.utils.cost_tracker import DegradationLevel, get_cost_summary, get_degradation_level
from src.utils.logger import get_logger

logger = get_logger("orchestrator")

# Dashboard event logger (fail-open import)
log_event: Callable[..., None] | None
try:
    from dashboard.backend.app.services.event_logger import log_event as _log_event
    log_event = _log_event
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    log_event = None


class Orchestrator:
    """Main orchestrator that wires all agents together."""

    def __init__(self, dry_run: bool = False, uov_diagnostic: bool = False) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run
        self.uov_diagnostic = uov_diagnostic
        self.state_machine = StateMachine()
        self.data_fetcher = DataFetcher()
        self.strategy_engine = StrategyEngine()
        self.moderation_panel = ModerationPanel()
        self.notification_service = NotificationService()
        self.risk_manager = RiskManager()
        self.opportunity_scorer = OpportunityScorer()
        self.opportunity_optimizer = OpportunityOptimizer()

        self._t212_client: T212Client | None = None
        self._order_manager: OrderManager | None = None
        self._stop_loss_manager: StopLossManager | None = None

    @property
    def t212_client(self) -> T212Client:
        if self._t212_client is None:
            self._t212_client = T212Client()
        return self._t212_client

    @property
    def order_manager(self) -> OrderManager:
        if self._order_manager is None:
            self._order_manager = OrderManager(client=self.t212_client, dry_run=self.dry_run)
        return self._order_manager

    @property
    def stop_loss_manager(self) -> StopLossManager:
        if self._stop_loss_manager is None:
            self._stop_loss_manager = StopLossManager(
                order_manager=self.order_manager,
                client=self.t212_client,
                dry_run=self.dry_run,
            )
        return self._stop_loss_manager

    def run_cycle(self, scheduled_cycle_id: str | None = None) -> dict[str, Any]:
        """Run a full investment cycle.

        Sequence: Data -> Strategy -> Moderation -> Risk -> Execution -> Journal

        When invoked by the scheduler, pass scheduled_cycle_id so a single Run record
        is used (scheduler creates it; orchestrator updates it on completion).
        """
        if scheduled_cycle_id:
            cycle_id = scheduled_cycle_id
        else:
            cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:6]}"
        logger.info(f"Starting cycle {cycle_id} (dry_run={self.dry_run})")

        # Ensure dashboard tables exist (fail-open; idempotent)
        if DASHBOARD_AVAILABLE and self.settings.dashboard_enabled and self.settings.dashboard_events_enabled:
            try:
                from dashboard.backend.app.database import init_dashboard_tables
                init_dashboard_tables()
            except Exception as e:
                logger.debug(f"Dashboard table init skipped: {e}")

        # Log run_started and create Run record only when NOT invoked by scheduler
        # (scheduler creates its own Run and passes scheduled_cycle_id)
        cycle_start_time = datetime.now(timezone.utc)
        if DASHBOARD_AVAILABLE and log_event is not None and not scheduled_cycle_id:
            try:
                log_event(
                    event_type="run_started",
                    source="orchestrator",
                    message=f"Cycle {cycle_id} starting (dry_run={self.dry_run})",
                    metadata={
                        "cycle_id": cycle_id,
                        "run_type": "manual" if not self.dry_run else "dry_run",
                        "started_at": cycle_start_time.isoformat(),
                    },
                )
                # Create run record (manual/dashboard trigger only)
                try:
                    from dashboard.backend.app.database import Run
                    session = get_session()
                    run = Run(
                        cycle_id=cycle_id,
                        run_type="manual" if not self.dry_run else "dry_run",
                        started_at=cycle_start_time,
                        status="running",
                    )
                    session.add(run)
                    session.commit()
                    session.close()
                    logger.debug(f"Created Run record for cycle {cycle_id}")
                except Exception as e:
                    logger.debug(f"Failed to create Run record (fail-open): {e}", exc_info=True)
            except Exception:
                pass  # Fail-open

        result: dict[str, Any] = {
            "cycle_id": cycle_id,
            "trades": [],
            "rejected_stocks": [],
            "errors": [],
            "opportunity_ranking": [],
            "queued_candidates": [],
            "swap_candidates": [],
        }
        strategy_decisions: list[dict[str, Any]] = []
        opportunity_evaluations: list[dict[str, Any]] = []
        stocks_data: list[dict[str, Any]] = []
        per_ticker_news: dict[str, str] = {}

        def _emit_cycle_summary() -> None:
            payload = self._build_cycle_summary_payload(
                cycle_id=cycle_id,
                result=result,
                strategy_decisions=strategy_decisions,
                opportunity_evaluations=opportunity_evaluations,
                stocks_data=stocks_data,
                per_ticker_news=per_ticker_news,
                dry_run=self.dry_run,
            )
            self.notification_service.emit_cycle_run_summary(
                cycle_id=cycle_id,
                payload=payload,
                source="orchestrator",
            )

        def _finalize(status: str) -> dict[str, Any]:
            result["status"] = status
            result["num_trades"] = len(result["trades"])
            rejected = result["rejected_stocks"]
            result["num_rejected"] = len(rejected)
            result["rejected_by_action"] = dict(Counter(r.get("action", "HOLD") for r in rejected))
            result["cost_summary"] = get_cost_summary(days=1)
            _emit_cycle_summary()
            
            # Log run_completed event (when called directly, not via scheduler)
            cycle_end_time = datetime.now(timezone.utc)
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    duration_seconds = (cycle_end_time - cycle_start_time).total_seconds()
                    log_event(
                        event_type="run_completed",
                        source="orchestrator",
                        message=f"Cycle {cycle_id} completed: {status} — {result['num_trades']} trades, {result['num_rejected']} rejected",
                        metadata={
                            "cycle_id": cycle_id,
                            "run_type": "manual" if not self.dry_run else "dry_run",
                            "status": status,
                            "duration_seconds": duration_seconds,
                            "num_trades": result["num_trades"],
                            "num_rejected": result["num_rejected"],
                        },
                    )
                    # Update run record
                    try:
                        from dashboard.backend.app.database import Run
                        session = get_session()
                        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                        if run:
                            run.completed_at = cycle_end_time
                            run.status = status
                            run.summary_json = {
                                "num_trades": result["num_trades"],
                                "num_rejected": result["num_rejected"],
                                "duration_seconds": duration_seconds,
                            }
                            session.commit()
                            logger.debug(f"Updated Run record for cycle {cycle_id}")
                        else:
                            logger.debug(f"Run record not found for cycle {cycle_id}, creating new one")
                            # Create if missing (scheduler Run creation may have failed)
                            run = Run(
                                cycle_id=cycle_id,
                                run_type="scheduled" if scheduled_cycle_id else ("manual" if not self.dry_run else "dry_run"),
                                started_at=cycle_start_time,
                                completed_at=cycle_end_time,
                                status=status,
                                summary_json={
                                    "num_trades": result["num_trades"],
                                    "num_rejected": result["num_rejected"],
                                    "duration_seconds": duration_seconds,
                                },
                            )
                            session.add(run)
                            session.commit()
                        session.close()
                    except Exception as e:
                        logger.warning(f"Failed to update Run record (fail-open): {e}", exc_info=True)
                except Exception:
                    pass  # Fail-open
            
            # Flush events before returning (ensure they're processed)
            if DASHBOARD_AVAILABLE:
                try:
                    from dashboard.backend.app.services.event_logger import flush_events
                    flush_events(timeout_seconds=2.0)
                except Exception:
                    pass  # Fail-open
            
            return result

        try:
            # Check if system is paused
            if self.state_machine.is_paused:
                logger.info("System is PAUSED. Skipping cycle.")
                return _finalize("paused")

            # Check cost degradation
            degradation = get_degradation_level()
            if degradation == DegradationLevel.HALTED:
                logger.error("All LLM budgets exceeded. Skipping cycle.")
                return _finalize("budget_halted")
            if degradation == DegradationLevel.NO_STRATEGY:
                logger.warning("Anthropic budget exceeded. Skipping strategy cycle.")
                return _finalize("budget_no_strategy")

            current_state = self.state_machine.current_state

            # --- STEP 1: HALTED state handling ---
            if current_state == "HALTED":
                logger.error("System is HALTED. Liquidating all positions.")
                if not self.dry_run:
                    liquidation = self.order_manager.liquidate_all()
                    result["liquidation"] = liquidation
                return _finalize("halted_liquidation")

            # --- STEP 2: Get portfolio state ---
            try:
                portfolio_data = self._get_portfolio_state()
            except Exception as e:
                logger.error(f"Failed to get portfolio state: {e}")
                result["errors"].append(f"portfolio_state: {e}")
                return _finalize("error")

            current_value = portfolio_data["total_value"]
            cash_gbp = portfolio_data["cash"]
            cash_pct = (cash_gbp / current_value * 100) if current_value > 0 else 100

            # Update peak and check drawdown
            if not self.dry_run:
                # Live: mutate DB state as normal
                self.state_machine.update_peak(current_value)
                state_info = self.state_machine.get_state()
                peak_value = state_info.get("peak_portfolio_value", current_value)

                drawdown_state = self.risk_manager.get_drawdown_state(current_value, peak_value)
                if drawdown_state != current_state:
                    self.state_machine.transition(drawdown_state, f"Drawdown check at {current_value:.2f}")
                    current_state = drawdown_state

                if current_state == "HALTED":
                    logger.error("Drawdown triggered HALT. Liquidating.")
                    self.order_manager.liquidate_all()
                    self._save_snapshot(portfolio_data, current_state)
                    return _finalize("halted_drawdown")

                drawdown_pct = ((peak_value - current_value) / peak_value * 100) if peak_value > 0 else 0
                self.state_machine.update_drawdown(drawdown_pct)
            else:
                # Dry-run: log what would happen but don't persist or block screening
                state_info = self.state_machine.get_state()
                peak_value = state_info.get("peak_portfolio_value", current_value)
                drawdown_pct = ((peak_value - current_value) / peak_value * 100) if peak_value > 0 else 0
                drawdown_state = self.risk_manager.get_drawdown_state(current_value, peak_value)
                if drawdown_state != "ACTIVE":
                    logger.info(
                        f"Dry-run: drawdown {drawdown_pct:.1f}% would trigger {drawdown_state}, "
                        f"ignoring (state not mutated in dry-run mode)"
                    )
                current_state = "ACTIVE"

            # --- STEP 3: Fetch market data ---
            logger.info("Fetching market data...")
            try:
                macro = self.data_fetcher.get_macro_data()
                vix = macro.get("vix")
                market_regime = macro.get("market_regime", "SIDEWAYS")
            except Exception as e:
                logger.error(f"Failed to get macro data: {e}")
                macro = {}
                vix = None
                market_regime = "SIDEWAYS"

            existing_tickers = {p.get("ticker", "") for p in portfolio_data.get("positions", [])}

            # Get data for current positions AND screen universe for new candidates
            stocks_data = self._fetch_stocks_data(
                current_positions=portfolio_data.get("positions", []),
                exclude_tickers=existing_tickers,
                system_state=current_state,
            )

            # --- STEP 4: Run strategies ---
            logger.info("Running strategies...")

            sub_results = self.strategy_engine.run_sub_strategies(stocks_data, existing_tickers)
            top_tickers = self._get_top_tickers(sub_results)

            # Deferred Finnhub/AV: only for positions ∪ top_tickers (active review)
            active_review_tickers = list(existing_tickers | set(top_tickers[:15]))[:15]

            # Get Alpha Vantage broad market sentiment (1 API call, cached 4h)
            av_broad_sentiment: dict[str, Any] = {}
            try:
                cached_broad = self.data_fetcher.get_cached_news_sentiment(
                    ticker=None, source="alpha_vantage", data_type="market_news_broad",
                )
                if cached_broad:
                    av_broad_sentiment = cached_broad
                else:
                    av_broad_sentiment = self.data_fetcher.alpha_vantage.get_broad_market_sentiment()
                    if "error" not in av_broad_sentiment:
                        self.data_fetcher.cache_news_sentiment(
                            ticker=None,
                            source="alpha_vantage",
                            data_type="market_news_broad",
                            data=av_broad_sentiment,
                            ttl_hours=self.settings.cache_ttl_hours("alpha_vantage_broad"),
                        )
            except Exception as e:
                logger.warning(f"Alpha Vantage broad sentiment unavailable: {e}")

            # Gather Finnhub analyst data (cached) for active-review tickers only
            analyst_data_map: dict[str, dict] = {}
            for ticker in active_review_tickers:
                try:
                    yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
                    analyst_data_map[ticker] = self.data_fetcher.get_analyst_data_cached(yf_ticker)
                except Exception as e:
                    logger.warning(f"Finnhub analyst data error for {ticker}: {e}")
                    analyst_data_map[ticker] = {}

            # Web search fallback when Finnhub returns error/unavailable (if enabled)
            if getattr(self.settings, "data_fallback_web_search_enabled", False):
                for ticker in active_review_tickers:
                    data = analyst_data_map.get(ticker, {})
                    if data.get("error") or data.get("unavailable"):
                        fallback = get_news_sentiment_fallback(ticker)
                        if fallback:
                            analyst_data_map[ticker] = {**data, "web_fallback": fallback}

            # Get Alpha Vantage ticker-specific news sentiment (1 API call for all tickers)
            av_ticker_sentiment: dict[str, Any] = {}
            av_all_articles: list[dict[str, Any]] = []
            if active_review_tickers:
                try:
                    yf_tickers = [t.replace("_US_EQ", "").replace("_UK_EQ", "") for t in active_review_tickers]
                    tickers_str = ",".join(yf_tickers)
                    # Single API call — returns both aggregate stats and raw articles
                    raw_data = self.data_fetcher.alpha_vantage.get_market_news_sentiment(
                        tickers=tickers_str, sort="RELEVANCE", limit=30,
                    )
                    if "error" not in raw_data:
                        av_all_articles = raw_data.get("articles", [])
                        av_ticker_sentiment = {
                            "tickers_queried": tickers_str,
                            "total_articles": raw_data.get("total_articles", 0),
                            "average_sentiment": raw_data.get("average_sentiment", 0),
                            "bullish_articles": raw_data.get("bullish_articles", 0),
                            "bearish_articles": raw_data.get("bearish_articles", 0),
                            "neutral_articles": raw_data.get("neutral_articles", 0),
                            "top_articles_summary": AlphaVantageClient._summarize_articles(
                                av_all_articles, max_articles=10,
                            ),
                        }
                except Exception as e:
                    logger.warning(f"Alpha Vantage ticker sentiment unavailable: {e}")

            # Extract per-ticker news from Alpha Vantage articles
            if av_all_articles:
                all_yf_tickers = [t.replace("_US_EQ", "").replace("_UK_EQ", "") for t in active_review_tickers]
                per_ticker_news = DataFetcher.extract_per_ticker_news(av_all_articles, all_yf_tickers)

            # Build per-ticker news sections for Claude (structured by ticker)
            news_parts: list[str] = []
            if per_ticker_news:
                news_parts.append("### Per-Ticker News Sentiment")
                for yf_t, news_text in per_ticker_news.items():
                    if news_text:
                        news_parts.append(f"\n**{yf_t}**:\n{news_text}")

            # Add aggregate ticker sentiment summary
            if av_ticker_sentiment and "error" not in av_ticker_sentiment:
                news_parts.append(f"\n### Aggregate Ticker News ({av_ticker_sentiment.get('tickers_queried', 'N/A')})")
                news_parts.append(f"Articles: {av_ticker_sentiment.get('total_articles', 0)} | "
                                  f"Avg sentiment: {av_ticker_sentiment.get('average_sentiment', 0):.4f} | "
                                  f"Bullish: {av_ticker_sentiment.get('bullish_articles', 0)} | "
                                  f"Bearish: {av_ticker_sentiment.get('bearish_articles', 0)}")
            elif active_review_tickers and getattr(self.settings, "data_fallback_web_search_enabled", False):
                fallback_blob = get_news_sentiment_fallback_batch(active_review_tickers)
                if fallback_blob:
                    news_parts.append("\n### Web Search Fallback (AV ticker sentiment unavailable)")
                    news_parts.append(fallback_blob)

            # Add broad market sentiment
            if av_broad_sentiment and "error" not in av_broad_sentiment:
                news_parts.append(f"\n### Broad Market Sentiment")
                news_parts.append(f"Articles: {av_broad_sentiment.get('total_articles', 0)} | "
                                  f"Avg sentiment: {av_broad_sentiment.get('average_sentiment', 0):.4f} | "
                                  f"Bullish: {av_broad_sentiment.get('bullish_articles', 0)} | "
                                  f"Bearish: {av_broad_sentiment.get('bearish_articles', 0)}")
                broad_articles = av_broad_sentiment.get("articles", [])
                if broad_articles:
                    broad_summary = AlphaVantageClient._summarize_articles(broad_articles, max_articles=10)
                    news_parts.append(broad_summary)

            # Add macro intelligence (sector trends + economic headlines)
            macro_intel = macro.get("macro_intelligence", {})
            if macro_intel.get("enabled"):
                if macro_intel.get("sector_summary"):
                    news_parts.append(f"\n### Sector Performance (S&P 500)")
                    news_parts.append(macro_intel["sector_summary"])
                if macro_intel.get("economic_highlights"):
                    news_parts.append(f"\n### Economic Highlights (Fed, tariffs, earnings)")
                    news_parts.append(macro_intel["economic_highlights"])

            analyst_summary = json.dumps(analyst_data_map, indent=2, default=str)[:3000]
            news_summary = "\n".join(news_parts)[:3000] if news_parts else "News sentiment data unavailable."

            # Build company profiles for top candidates
            all_stock_tickers = [s.get("ticker", "") for s in stocks_data if s.get("ticker")][:35]
            company_profiles = self._build_company_profiles(stocks_data, all_stock_tickers)
            uov_swap_context = self.opportunity_scorer.build_swap_context(existing_tickers)

            # Claude synthesis
            portfolio_state_str = json.dumps(portfolio_data, indent=2, default=str)[:2000]
            strategy_result = self.strategy_engine.synthesize_with_claude(
                sub_strategy_results=sub_results,
                portfolio_state=portfolio_state_str,
                market_regime=market_regime,
                analyst_data=analyst_summary,
                news_sentiment=news_summary,
                company_profiles=company_profiles,
                system_state=current_state,
                vix=vix,
                cash_pct=cash_pct,
                num_positions=len(existing_tickers),
                cycle_id=cycle_id,
                uov_swap_context=uov_swap_context,
            )

            if "error" in strategy_result and not strategy_result.get("decisions"):
                logger.error(f"Strategy synthesis failed: {strategy_result['error']}")
                result["errors"].append(f"strategy: {strategy_result['error']}")
                if not self.dry_run:
                    self.state_machine.record_cycle()
                self._save_snapshot(portfolio_data, current_state)
                return _finalize("strategy_error")

            decisions = strategy_result.get("decisions", [])
            strategy_decisions = decisions
            logger.info(f"Strategy produced {len(decisions)} decisions")

            # Research executor for moderation tool-use (shared budget per cycle)
            research_executor = None
            if self.settings.research_enabled and (
                self.settings.skeptic_research_enabled or self.settings.risk_research_enabled
            ):
                from src.agents.research import ResearchExecutor
                research_executor = ResearchExecutor(cycle_id=cycle_id)
            
            # Log strategy decisions
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    for decision in decisions:
                        log_event(
                            event_type="decision_made",
                            source="strategy",
                            message=f"{decision.get('action', 'HOLD')} {decision.get('ticker', 'UNKNOWN')} - {decision.get('reasoning', '')[:100]}",
                            metadata={
                                "cycle_id": cycle_id,
                                "ticker": decision.get("ticker"),
                                "action": decision.get("action"),
                                "conviction": decision.get("conviction"),
                                "target_allocation_pct": decision.get("target_allocation_pct"),
                                "reasoning": decision.get("reasoning", "")[:500],  # Truncate for storage
                            },
                        )
                except Exception:
                    pass  # Fail-open

            # --- STEP 5: Moderation -> Risk -> (Deferred BUY Execution) ---
            pending_buys: list[dict[str, Any]] = []
            projected_num_positions = len(existing_tickers)

            for decision in decisions:
                raw_ticker = str(decision.get("ticker", "")).strip().upper()
                ticker = self._normalize_decision_ticker(raw_ticker, stocks_data)
                if raw_ticker and ticker != raw_ticker:
                    logger.warning(f"Normalized strategy ticker '{raw_ticker}' -> '{ticker}'")
                    decision["ticker"] = ticker
                action = decision.get("action", "HOLD")
                conviction = decision.get("conviction", 0)
                target_alloc = decision.get("target_allocation_pct", 0)

                if action in ("HOLD", "QUEUED"):
                    hold_reason = decision.get("reasoning", f"{action} — no action this cycle")
                    result["rejected_stocks"].append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "strategy_hold" if action == "HOLD" else "strategy_queued",
                        "reason": hold_reason,
                        "conviction": conviction,
                        "moderation_consensus": "not invoked",
                        **self._get_stock_metadata(ticker, stocks_data),
                    })
                    opportunity_evaluations.append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "strategy_queued" if action == "QUEUED" else "strategy_hold",
                        "decision": decision,
                        "reason": hold_reason,
                        "moderation_consensus": "not invoked",
                        "risk_verdict": "not invoked",
                        "final_allocation_pct": None,
                    })
                    continue

                # Moderation — build rich market context for moderators
                logger.info(f"Moderating {action} {ticker}...")
                yf_ticker_for_news = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
                ticker_news = per_ticker_news.get(yf_ticker_for_news, "")
                sector = self._get_sector(ticker, stocks_data)
                market_context = self._build_market_context(
                    ticker=ticker,
                    stocks_data=stocks_data,
                    sub_results=sub_results,
                    macro=macro,
                    market_regime=market_regime,
                    vix=vix,
                    analyst_data_map=analyst_data_map,
                    news_summary=news_summary,
                    ticker_news=ticker_news,
                    strategy_assessment=strategy_result.get("market_assessment", ""),
                    sector=sector,
                )

                mod_result = self.moderation_panel.review_trade(
                    trade_proposal=decision,
                    portfolio_context=portfolio_state_str,
                    market_context=market_context,
                    conviction=conviction,
                    cycle_id=cycle_id,
                    research_executor=research_executor,
                )
                mod_dict = mod_result.to_dict()
                
                # Log moderation decision
                if DASHBOARD_AVAILABLE and log_event is not None:
                    try:
                        log_event(
                            event_type="decision_made",
                            source="moderation",
                            message=f"Moderation {mod_result.consensus} for {action} {ticker}",
                            metadata={
                                "cycle_id": cycle_id,
                                "ticker": ticker,
                                "action": action,
                                "consensus": mod_result.consensus,
                                "gpt_score": mod_result.gpt_score,
                                "gemini_score": mod_result.gemini_score,
                                "gpt_reasoning": mod_result.gpt_reasoning[:500] if mod_result.gpt_reasoning else None,
                                "gemini_reasoning": mod_result.gemini_reasoning[:500] if mod_result.gemini_reasoning else None,
                            },
                        )
                    except Exception:
                        pass  # Fail-open

                if mod_result.consensus == "BLOCKED":
                    logger.info(f"{ticker} BLOCKED by moderation panel")
                    reason = "BLOCKED by moderation consensus"
                    result["rejected_stocks"].append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "moderation",
                        "reason": reason,
                        "conviction": conviction,
                        "moderation": mod_result.consensus,
                        **self._get_stock_metadata(ticker, stocks_data),
                    })
                    opportunity_evaluations.append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "moderation_blocked",
                        "decision": decision,
                        "moderation": mod_dict,
                        "reason": reason,
                        "moderation_consensus": mod_result.consensus,
                        "risk_verdict": None,
                        "final_allocation_pct": None,
                    })
                    continue

                # Risk check
                logger.info(f"Risk check for {action} {ticker}...")
                sector = self._get_sector(ticker, stocks_data)
                sector_allocs = self._get_sector_allocations(portfolio_data)
                portfolio_allocs = self._get_position_allocations(portfolio_data)

                risk_verdict = self.risk_manager.evaluate_trade(
                    ticker=ticker,
                    action=action,
                    proposed_allocation_pct=target_alloc,
                    sector=sector,
                    current_portfolio=portfolio_allocs,
                    sector_allocations=sector_allocs,
                    portfolio_returns={},
                    current_value=current_value,
                    peak_value=peak_value,
                    cash_pct=cash_pct,
                    vix=vix,
                    daily_pnl_pct=portfolio_data.get("daily_pnl_pct", 0),
                    daily_loss_halt_until=state_info.get("daily_loss_halt_until"),
                    num_positions=projected_num_positions,
                    system_state=current_state,
                    is_existing_winner=ticker in existing_tickers,
                    cycle_id=cycle_id,
                )
                
                # Log risk decision
                if DASHBOARD_AVAILABLE and log_event is not None:
                    try:
                        log_event(
                            event_type="decision_made",
                            source="risk",
                            message=f"Risk {risk_verdict.verdict} for {action} {ticker}: {risk_verdict.reasoning[:100]}",
                            metadata={
                                "cycle_id": cycle_id,
                                "ticker": ticker,
                                "action": action,
                                "verdict": risk_verdict.verdict,
                                "triggered_rules": risk_verdict.triggered_rules,
                                "reasoning": risk_verdict.reasoning[:500] if risk_verdict.reasoning else None,
                                "adjusted_allocation_pct": risk_verdict.adjusted_allocation_pct,
                            },
                        )
                    except Exception:
                        pass  # Fail-open

                if risk_verdict.verdict == "REJECT":
                    logger.info(f"{ticker} REJECTED by risk: {risk_verdict.reasoning}")
                    result["rejected_stocks"].append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "risk",
                        "reason": risk_verdict.reasoning,
                        "conviction": conviction,
                        "moderation": mod_result.consensus,
                        "triggered_rules": risk_verdict.triggered_rules,
                        **self._get_stock_metadata(ticker, stocks_data),
                    })
                    opportunity_evaluations.append({
                        "ticker": ticker,
                        "action": action,
                        "stage": "risk_reject",
                        "decision": decision,
                        "moderation": mod_dict,
                        "reason": risk_verdict.reasoning,
                        "moderation_consensus": mod_result.consensus,
                        "risk_verdict": risk_verdict.verdict,
                        "final_allocation_pct": None,
                    })
                    continue

                final_alloc = risk_verdict.adjusted_allocation_pct or target_alloc
                stage = "risk_resize" if (action == "BUY" and risk_verdict.verdict == "RESIZE") else "approved"
                opportunity_evaluations.append({
                    "ticker": ticker,
                    "action": action,
                    "stage": stage,
                    "decision": decision,
                    "moderation": mod_dict,
                    "reason": decision.get("reasoning", ""),
                    "moderation_consensus": mod_result.consensus,
                    "risk_verdict": risk_verdict.verdict,
                    "final_allocation_pct": final_alloc,
                })

                self.notification_service.emit_trade_instruction_approved(
                    cycle_id=cycle_id,
                    payload={
                        "cycle_id": cycle_id,
                        "dry_run": self.dry_run,
                        "ticker": ticker,
                        "action": action,
                        "target_allocation_pct": target_alloc,
                        "final_allocation_pct": final_alloc,
                        "conviction": conviction,
                        "moderation_consensus": mod_result.consensus,
                        "risk_verdict": risk_verdict.verdict,
                        "reasoning_summary": decision.get("reasoning", ""),
                        **self._get_stock_metadata(ticker, stocks_data),
                    },
                )

                if action == "BUY":
                    pending_buys.append({
                        "ticker": ticker,
                        "action": action,
                        "decision": decision,
                        "moderation": mod_result,
                        "risk_verdict": risk_verdict,
                        "final_allocation_pct": final_alloc,
                    })
                    continue

                trade_entry = self._execute_trade(
                    cycle_id=cycle_id,
                    decision=decision,
                    action=action,
                    ticker=ticker,
                    final_alloc=final_alloc,
                    current_value=current_value,
                    cash_gbp=cash_gbp,
                    total_return_pct=portfolio_data.get("total_return_pct", 0),
                    alpha_pct=portfolio_data.get("alpha_pct", 0),
                    existing_tickers=existing_tickers,
                    market_regime=market_regime,
                    vix=vix,
                    macro=macro,
                    stocks_data=stocks_data,
                    analyst_data_map=analyst_data_map,
                    av_broad_sentiment=av_broad_sentiment,
                    mod_result=mod_result,
                    risk_verdict=risk_verdict,
                )
                if trade_entry:
                    result["trades"].append(trade_entry)
                    if action == "SELL" and trade_entry.get("execution", {}).get("status") in ("filled", "dry_run"):
                        projected_num_positions = max(0, projected_num_positions - 1)

            # --- STEP 6: UOV scoring + BUY optimization ---
            selected_buy_order = [b["ticker"] for b in pending_buys]
            if self.settings.opportunity_enabled:
                scores = self.opportunity_scorer.score_cycle(
                    cycle_id=cycle_id,
                    evaluations=opportunity_evaluations,
                    sub_results=sub_results,
                    stocks_data=stocks_data,
                    per_ticker_news=per_ticker_news,
                )
                result["opportunity_ranking"] = [s.to_dict() for s in scores]
                scores_by_ticker = {entry["ticker"]: entry for entry in result["opportunity_ranking"]}
                if not scores_by_ticker and pending_buys:
                    logger.warning("UOV scoring unavailable, falling back to legacy BUY execution order.")
                else:
                    plan = self.opportunity_optimizer.optimize_buys(
                        cycle_id=cycle_id,
                        approved_buys=pending_buys,
                        scores_by_ticker=scores_by_ticker,
                        existing_tickers=existing_tickers,
                        cash_pct=cash_pct,
                        num_positions=projected_num_positions,
                    )
                    result["queued_candidates"] = plan.get("queued_candidates", [])
                    result["swap_candidates"] = plan.get("swap_candidates", [])

                    if self.settings.opportunity_mode == "active" and not self.uov_diagnostic:
                        selected_buy_order = plan.get("execution_order", selected_buy_order)
                        selected_set = set(selected_buy_order)
                        rejection_details = plan.get("rejection_details", {})
                        for pending in pending_buys:
                            ticker = pending.get("ticker", "")
                            if ticker in selected_set:
                                continue
                            details = rejection_details.get(ticker, {})
                            stage = details.get("stage", "opportunity_filtered")
                            reason = details.get("reason_message", "Filtered by UOV optimizer")
                            score_info = scores_by_ticker.get(ticker, {})
                            uov_ewma = score_info.get("uov_ewma")
                            uov_z = score_info.get("uov_z")
                            rejected_entry: dict[str, Any] = {
                                "ticker": ticker,
                                "action": "BUY",
                                "stage": stage,
                                "reason": reason,
                                "stage_reason_code": details.get("reason_code"),
                                "conviction": pending.get("decision", {}).get("conviction", 0),
                                **self._get_stock_metadata(ticker, stocks_data),
                            }
                            if uov_ewma is not None:
                                rejected_entry["uov_ewma"] = round(float(uov_ewma), 4)
                            if uov_z is not None:
                                rejected_entry["uov_z"] = round(float(uov_z), 4)
                            result["rejected_stocks"].append(rejected_entry)

            pending_by_ticker = {b["ticker"]: b for b in pending_buys}
            for ticker in selected_buy_order:
                pending = pending_by_ticker.get(ticker)
                if pending is None:
                    continue

                decision = pending["decision"]
                entry_type = str(decision.get("entry_type", "market")).lower()

                # Limit dip-buy: place limit order below current price
                if (
                    entry_type == "limit_dip"
                    and self.settings.order_management_enabled
                    and self.settings.limit_orders_enabled
                ):
                    final_alloc = float(pending.get("final_allocation_pct", 0.0))
                    trade_value = current_value * final_alloc / 100
                    price = self._get_current_price(ticker, stocks_data)
                    if price > 0:
                        limit_result = self.stop_loss_manager.place_limit_buy(
                            ticker=ticker,
                            target_amount_gbp=trade_value,
                            current_price=price,
                            offset_pct=decision.get("limit_offset_pct"),
                            strategy=decision.get("primary_strategy"),
                            conviction=decision.get("conviction"),
                            cycle_id=cycle_id,
                        )
                        result["trades"].append({
                            "ticker": ticker,
                            "action": "BUY",
                            "order_type": "limit",
                            "allocation_pct": final_alloc,
                            "execution": limit_result,
                            "moderation": pending["moderation"].consensus,
                            "risk": pending["risk_verdict"].verdict,
                        })
                        self.notification_service.emit_order_adjustment(
                            cycle_id=cycle_id,
                            payload={
                                "cycle_id": cycle_id,
                                "dry_run": self.dry_run,
                                "ticker": ticker,
                                "adjustment_type": "limit_order",
                                "new_stop_price": limit_result.get("limit_price"),
                                "current_price": price,
                                "status": limit_result.get("status"),
                            },
                        )
                    continue

                trade_entry = self._execute_trade(
                    cycle_id=cycle_id,
                    decision=decision,
                    action="BUY",
                    ticker=ticker,
                    final_alloc=float(pending.get("final_allocation_pct", 0.0)),
                    current_value=current_value,
                    cash_gbp=cash_gbp,
                    total_return_pct=portfolio_data.get("total_return_pct", 0),
                    alpha_pct=portfolio_data.get("alpha_pct", 0),
                    existing_tickers=existing_tickers,
                    market_regime=market_regime,
                    vix=vix,
                    macro=macro,
                    stocks_data=stocks_data,
                    analyst_data_map=analyst_data_map,
                    av_broad_sentiment=av_broad_sentiment,
                    mod_result=pending["moderation"],
                    risk_verdict=pending["risk_verdict"],
                )
                if trade_entry:
                    result["trades"].append(trade_entry)

            # --- STEP 7: Intelligent order management (stop-loss reassessment) ---
            if self.settings.order_management_enabled:
                try:
                    current_positions = portfolio_data.get("positions", [])
                    all_adjustments: list[dict[str, Any]] = []

                    # Reassess stops using ATR-based volatility
                    if self.settings.reassess_stops_enabled:
                        reassess_results = self.stop_loss_manager.reassess_stops(
                            positions=current_positions,
                            stocks_data=stocks_data,
                            cycle_id=cycle_id,
                        )
                        all_adjustments.extend(reassess_results)

                    # Apply trailing stops
                    if self.settings.trailing_stops_enabled:
                        trailing_results = self.stop_loss_manager.apply_trailing_stops(
                            positions=current_positions,
                            cycle_id=cycle_id,
                        )
                        all_adjustments.extend(trailing_results)

                    result["order_adjustments"] = all_adjustments

                    if all_adjustments:
                        logger.info(
                            f"Order management: {len(all_adjustments)} stop-loss adjustments"
                        )
                        self.notification_service.emit_order_adjustment(
                            cycle_id=cycle_id,
                            payload={
                                "cycle_id": cycle_id,
                                "dry_run": self.dry_run,
                                "adjustment_type": "batch",
                                "adjustments": all_adjustments,
                            },
                        )
                except Exception as om_err:
                    logger.warning(f"Order management phase skipped: {om_err}")
                    result["errors"].append(f"order_management: {om_err}")

            # Record cycle completion
            if not self.dry_run:
                self.state_machine.record_cycle()
            self._save_snapshot(portfolio_data, current_state)
            try:
                update_trade_outcomes()
                update_performance_metrics()
            except Exception as perf_err:
                logger.warning(f"Performance/trade-outcome update skipped: {perf_err}")

            logger.info(f"Cycle {cycle_id} completed: {len(result['trades'])} trades executed, "
                        f"{len(result['rejected_stocks'])} rejected")
            return _finalize("completed")
        except Exception as e:
            logger.exception(f"Unhandled cycle failure in {cycle_id}: {e}")
            result["errors"].append(f"unhandled: {e}")
            result["status"] = "error"
            self.notification_service.emit_critical_cycle_failure(
                cycle_id=cycle_id,
                payload={
                    "cycle_id": cycle_id,
                    "dry_run": self.dry_run,
                    "stage": "run_cycle",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "trace_id": cycle_id,
                },
                source="orchestrator",
            )
            _emit_cycle_summary()
            raise

    # --- Helper methods ---

    def _get_portfolio_state(self) -> dict[str, Any]:
        """Get current portfolio state from T212."""
        mock_state = {
            "cash": 10000.0,
            "total_value": 10000.0,
            "invested": 0.0,
            "positions": [],
            "num_positions": 0,
            "daily_pnl_pct": 0.0,
            "total_return_pct": 0.0,
            "alpha_pct": 0.0,
        }

        try:
            state = self.order_manager.get_portfolio_state()
        except Exception:
            if self.dry_run:
                logger.info("T212 API unavailable, using mock portfolio for dry-run")
                return mock_state
            raise

        # order_manager catches errors internally and returns an error dict
        if state.get("error"):
            if self.dry_run:
                logger.info("T212 API returned error, using mock portfolio for dry-run")
                return mock_state
            raise RuntimeError(f"Failed to get portfolio state: {state['error']}")

        cash_data = state.get("cash", {})
        positions = state.get("positions", [])
        summary = state.get("account_summary") or {}

        # Prefer totalValue from account summary — authoritative total including reserved
        total_value_raw = summary.get("totalValue")
        if total_value_raw is not None:
            total_value = float(total_value_raw)
        else:
            # Fallback: piece together from cash + positions (cash endpoint may omit reserved)
            if isinstance(cash_data, dict):
                cash = float(cash_data.get("free", cash_data.get("availableToTrade", 0)))
                reserved = float(
                    cash_data.get("reservedForOrders", cash_data.get("blocked", cash_data.get("reserved", 0)))
                )
            else:
                cash = float(cash_data)
                reserved = 0.0
            invested = sum(
                float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
                for p in positions
            )
            total_value = cash + invested + reserved

        # Cash for allocation logic: free/available only
        if isinstance(cash_data, dict):
            cash = float(cash_data.get("free", cash_data.get("availableToTrade", 0)))
        else:
            cash = float(cash_data)
        invested = sum(
            float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
            for p in positions
        )

        return {
            "cash": cash,
            "total_value": total_value,
            "invested": invested,
            "positions": positions,
            "num_positions": len(positions),
            "daily_pnl_pct": 0.0,
            "total_return_pct": ((total_value / 10000) - 1) * 100 if total_value > 0 else 0,
            "alpha_pct": 0.0,
        }

    def _fetch_stocks_data(
        self,
        current_positions: list[dict],
        exclude_tickers: set[str] | None = None,
        system_state: str = "ACTIVE",
    ) -> list[dict[str, Any]]:
        """Fetch analysis data for current positions + screened universe candidates.

        Two phases:
        1. Analyze all current positions (always).
        2. Screen the instrument universe for new candidates using sector-balanced,
           market-cap-tiered sampling (skip in CAUTIOUS — no new positions allowed).

        When cycle_frequency is intraday: uses get_stock_analysis_lite (Tier 1 only,
        no Finnhub) for screening. Finnhub/AV fetched later for active-review tickers.
        When standard: uses get_stock_analysis (includes Finnhub) for backward compat.
        """
        use_lite = self.settings.cycle_frequency == "intraday"
        cache_key = "lite_analysis" if use_lite else "full_analysis"
        fetch_fn = self.data_fetcher.get_stock_analysis_lite if use_lite else self.data_fetcher.get_stock_analysis

        stocks_data: list[dict[str, Any]] = []
        analyzed_tickers: set[str] = set()

        # Phase 1: Analyze current positions
        for pos in current_positions:
            ticker = pos.get("ticker", "")
            if not ticker:
                continue
            yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
            try:
                cached = self.data_fetcher.get_cached_data(yf_ticker, cache_key)
                if cached:
                    cached["ticker"] = ticker
                    stocks_data.append(cached)
                else:
                    data = fetch_fn(yf_ticker)
                    data["ticker"] = ticker
                    stocks_data.append(data)
                    self.data_fetcher.enrich_instrument_metadata(
                        ticker, data.get("fundamentals", {}),
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch data for {ticker}: {e}")
                stocks_data.append({"ticker": ticker, "indicators": {}, "fundamentals": {}})
            analyzed_tickers.add(ticker)

        # Phase 2: Screen universe for new candidates (not in CAUTIOUS mode)
        if system_state != "CAUTIOUS":
            all_exclude = analyzed_tickers | (exclude_tickers or set())
            try:
                candidates = self.data_fetcher.get_screened_universe(
                    exclude_tickers=all_exclude,
                )
                self.data_fetcher.mark_instruments_screened(
                    [c["ticker"] for c in candidates],
                )
                logger.info(f"Screening {len(candidates)} universe candidates...")
                skipped_no_data = 0
                for candidate in candidates:
                    c_ticker = candidate["ticker"]
                    yf_ticker = c_ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
                    if c_ticker in analyzed_tickers:
                        continue
                    try:
                        cached = self.data_fetcher.get_cached_data(yf_ticker, cache_key)
                        if cached:
                            if cached.get("indicators", {}).get("error"):
                                skipped_no_data += 1
                                continue
                            cached["ticker"] = c_ticker
                            stocks_data.append(cached)
                        else:
                            data = fetch_fn(yf_ticker)
                            data["ticker"] = c_ticker
                            if data.get("indicators", {}).get("error"):
                                logger.debug(f"Skipping {c_ticker}: no OHLCV data available")
                                self.data_fetcher.mark_instrument_unavailable(c_ticker)
                                skipped_no_data += 1
                                continue
                            stocks_data.append(data)
                            self.data_fetcher.enrich_instrument_metadata(
                                c_ticker, data.get("fundamentals", {}),
                            )
                    except Exception as e:
                        logger.warning(f"Failed to fetch data for candidate {c_ticker}: {e}")
                    analyzed_tickers.add(c_ticker)
                if skipped_no_data:
                    logger.info(f"Skipped {skipped_no_data} candidates with no OHLCV data")
            except Exception as e:
                logger.warning(f"Universe screening failed: {e}")

        logger.info(f"Total stocks analyzed: {len(stocks_data)} "
                     f"(positions: {len(current_positions)}, "
                     f"candidates: {len(stocks_data) - len(current_positions)})")
        return stocks_data

    def _execute_trade(
        self,
        cycle_id: str,
        decision: dict[str, Any],
        action: str,
        ticker: str,
        final_alloc: float,
        current_value: float,
        cash_gbp: float,
        total_return_pct: float,
        alpha_pct: float,
        existing_tickers: set[str],
        market_regime: str,
        vix: float | None,
        macro: dict[str, Any],
        stocks_data: list[dict[str, Any]],
        analyst_data_map: dict[str, dict],
        av_broad_sentiment: dict[str, Any],
        mod_result: Any,
        risk_verdict: Any,
    ) -> dict[str, Any] | None:
        """Execute an approved trade and generate journal + stop-loss where relevant."""
        trade_value = current_value * final_alloc / 100
        current_price = self._get_current_price(ticker, stocks_data)

        if current_price <= 0:
            logger.warning(f"No price for {ticker}, skipping")
            self.notification_service.emit_trade_execution_result(
                cycle_id=cycle_id,
                payload={
                    "cycle_id": cycle_id,
                    "dry_run": self.dry_run,
                    "ticker": ticker,
                    "action": action,
                    "execution_status": "skipped",
                    "quantity": 0,
                    "price": None,
                    "value_gbp": None,
                    "stop_loss_pct": decision.get("stop_loss_pct", 0),
                    "stop_loss_status": None,
                    "error_message": "no_price",
                    "reasoning_summary": decision.get("reasoning", ""),
                    "target_allocation_pct": final_alloc,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return None

        conviction = decision.get("conviction", 0)
        logger.info(f"Executing {action} {ticker} at {final_alloc:.1f}%...")
        exec_result = self.order_manager.execute_market_order(
            ticker=ticker,
            action=action,
            target_amount_gbp=trade_value,
            current_price=current_price,
            strategy=decision.get("primary_strategy"),
            conviction=conviction,
            moderation_result=mod_result.consensus,
            risk_result=risk_verdict.verdict,
        )

        try:
            stock_data = next((s for s in stocks_data if s["ticker"] == ticker), {})
            journal_path = generate_trade_journal(
                action=action,
                ticker=ticker,
                shares=exec_result.get("quantity", 0),
                price=current_price,
                value_gbp=exec_result.get("value_gbp", trade_value),
                weight_pct=final_alloc,
                conviction=conviction,
                strategy=decision.get("primary_strategy", "unknown"),
                reasoning=decision.get("reasoning", ""),
                growth_potential=decision.get("growth_potential", "MEDIUM"),
                risk_level=decision.get("risk_level", "MEDIUM"),
                catalysts=decision.get("catalysts", []),
                risks=decision.get("risks", []),
                exit_conditions=decision.get("exit_conditions", ""),
                upside_target_pct=decision.get("upside_target_pct", 0),
                stop_loss_pct=decision.get("stop_loss_pct", 0),
                expected_holding_period=decision.get("expected_holding_period", ""),
                market_regime=market_regime,
                vix=vix,
                sp500_trend=macro.get("sp500_pct_above_200ma", "N/A"),
                news_sentiment_overall=decision.get("news_sentiment_summary", ""),
                finnhub_data=analyst_data_map.get(ticker, {}),
                alpha_vantage_data=av_broad_sentiment,
                moderation_results=mod_result.to_dict(),
                risk_verdict={
                    "verdict": risk_verdict.verdict,
                    "rules_checked": risk_verdict.rules_checked,
                    "triggered_rules": risk_verdict.triggered_rules,
                    "reasoning": risk_verdict.reasoning,
                },
                indicators=stock_data.get("indicators", {}),
                fundamentals=stock_data.get("fundamentals", {}),
                portfolio_state={
                    "total_value": current_value,
                    "cash": cash_gbp,
                    "invested": current_value - cash_gbp,
                    "num_positions": len(existing_tickers),
                    "total_return_pct": total_return_pct,
                    "alpha_pct": alpha_pct,
                    "positions": [],
                },
            )
            exec_result["journal_path"] = journal_path
        except Exception as e:
            logger.error(f"Journal generation failed for {ticker}: {e}")

        stop_loss_result = None
        stop_loss_pct = decision.get("stop_loss_pct", 0)
        if (
            action == "BUY"
            and exec_result.get("status") in ("filled", "dry_run")
            and stop_loss_pct
            and stop_loss_pct < 0
        ):
            executed_qty = exec_result.get("quantity", 0)
            if executed_qty > 0:
                try:
                    stop_loss_result = self.order_manager.place_stop_loss(
                        ticker=ticker,
                        quantity=executed_qty,
                        current_price=current_price,
                        stop_loss_pct=stop_loss_pct,
                        strategy=decision.get("primary_strategy"),
                    )
                    logger.info(
                        f"Stop-loss for {ticker}: {stop_loss_result.get('status')} "
                        f"@ {stop_loss_result.get('stop_price')}"
                    )
                except Exception as e:
                    logger.error(f"Failed to place stop-loss for {ticker}: {e}")

        self.notification_service.emit_trade_execution_result(
            cycle_id=cycle_id,
            payload={
                "cycle_id": cycle_id,
                "dry_run": self.dry_run,
                "ticker": ticker,
                "action": action,
                "target_allocation_pct": final_alloc,
                "execution_status": exec_result.get("status"),
                "quantity": exec_result.get("quantity"),
                "price": current_price,
                "value_gbp": exec_result.get("value_gbp", trade_value),
                "stop_loss_pct": stop_loss_pct,
                "stop_loss_status": (stop_loss_result or {}).get("status"),
                "stop_loss_error": (stop_loss_result or {}).get("error"),
                "error_message": exec_result.get("error"),
                "reasoning_summary": decision.get("reasoning", ""),
                "moderation_consensus": mod_result.consensus,
                "risk_verdict": risk_verdict.verdict,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return {
            "ticker": ticker,
            "action": action,
            "allocation_pct": final_alloc,
            "reasoning": decision.get("reasoning", ""),
            **self._get_stock_metadata(ticker, stocks_data),
            "execution": exec_result,
            "moderation": mod_result.consensus,
            "risk": risk_verdict.verdict,
            "stop_loss": stop_loss_result,
        }

    def _get_top_tickers(self, sub_results: dict[str, Any]) -> list[str]:
        """Extract top tickers from sub-strategy results."""
        tickers: set[str] = set()
        for signal in sub_results.get("momentum", []):
            if signal.action == "BUY" and signal.score >= 75:
                tickers.add(signal.ticker)
        for signal in sub_results.get("mean_reversion", []):
            if signal.action == "BUY" and signal.score >= 70:
                tickers.add(signal.ticker)
        for score in sub_results.get("top_factor", []):
            tickers.add(score.ticker)
        return list(tickers)

    @staticmethod
    def _build_company_profiles(
        stocks_data: list[dict[str, Any]],
        top_tickers: list[str],
    ) -> str:
        """Build compact company profile text for Claude from fundamentals data.

        Extracts business_summary, industry, and sector for each top candidate
        so Claude can reason about qualitative factors like competitive moats,
        regulatory risk, and how macro news impacts the business.
        """
        profiles: list[str] = []
        # Build lookup from stocks_data
        data_by_ticker: dict[str, dict] = {}
        for stock in stocks_data:
            data_by_ticker[stock.get("ticker", "")] = stock

        for ticker in top_tickers[:35]:
            stock = data_by_ticker.get(ticker, {})
            fundamentals = stock.get("fundamentals", {})
            summary = fundamentals.get("business_summary", "")
            industry = fundamentals.get("industry", "")
            sector = fundamentals.get("sector", "")
            name = stock.get("name", ticker)

            if not summary:
                continue

            # Truncate long summaries to ~300 chars to keep prompt compact
            if len(summary) > 300:
                summary = summary[:297] + "..."

            header = f"**{ticker}** ({name})"
            if industry:
                header += f" | {industry}"
            elif sector:
                header += f" | {sector}"

            profiles.append(f"{header}\n{summary}")

        if not profiles:
            return "Company profile data not yet available for these tickers."
        return "\n\n".join(profiles)

    def _build_market_context(
        self,
        ticker: str,
        stocks_data: list[dict],
        sub_results: dict[str, Any],
        macro: dict[str, Any],
        market_regime: str,
        vix: float | None,
        analyst_data_map: dict[str, dict],
        news_summary: str,
        ticker_news: str = "",
        strategy_assessment: str = "",
        sector: str = "Unknown",
    ) -> dict[str, Any]:
        """Build rich market context dict for moderator review.

        Gives moderators the same data quality as the strategy agent:
        technical indicators, fundamentals, market regime, sub-strategy
        signals, analyst data, news sentiment, sector headwinds, economic
        highlights, and Claude's market assessment.
        """
        # Find stock-specific data
        stock_data = next((s for s in stocks_data if s.get("ticker") == ticker), {})
        indicators = stock_data.get("indicators", {})
        fundamentals = stock_data.get("fundamentals", {})

        # Find sub-strategy signals for this ticker
        momentum_signal = None
        for s in sub_results.get("momentum", []):
            if s.ticker == ticker:
                momentum_signal = {
                    "action": s.action,
                    "score": s.score,
                    "reasoning": s.reasoning,
                }
                break

        mean_reversion_signal = None
        for s in sub_results.get("mean_reversion", []):
            if s.ticker == ticker:
                mean_reversion_signal = {
                    "action": s.action,
                    "score": s.score,
                    "reasoning": s.reasoning,
                }
                break

        factor_signal = None
        for s in sub_results.get("factor", []):
            if s.ticker == ticker:
                factor_signal = {
                    "composite_score": s.composite_score,
                    "value_score": s.value_score,
                    "quality_score": s.quality_score,
                    "momentum_score": s.momentum_score,
                    "reasoning": s.reasoning,
                }
                break

        # Build news: prefer per-ticker news, fall back to combined summary
        effective_news = ""
        if ticker_news:
            effective_news = ticker_news
        elif news_summary and news_summary != "News sentiment data unavailable.":
            effective_news = news_summary

        macro_intel = macro.get("macro_intelligence", {})
        sector_headwind = (
            get_sector_headwind(macro_intel, sector) if macro_intel.get("enabled") else None
        )
        economic_highlights = macro_intel.get("economic_highlights", "")
        sector_summary = macro_intel.get("sector_summary", "")

        return {
            "indicators": indicators,
            "fundamentals": fundamentals,
            "macro": {
                "vix": vix,
                "market_regime": market_regime,
                "sp500_above_200ma": macro.get("sp500_above_200ma"),
                "sector_headwind": sector_headwind,
                "economic_highlights": economic_highlights,
                "sector_summary": sector_summary,
            },
            "sub_strategies": {
                "momentum": momentum_signal,
                "mean_reversion": mean_reversion_signal,
                "factor": factor_signal,
            },
            "analyst_data": analyst_data_map.get(ticker, {}),
            "news_sentiment": effective_news,
            "strategy_assessment": strategy_assessment,
        }

    def _get_sector(self, ticker: str, stocks_data: list[dict]) -> str:
        for s in stocks_data:
            if s.get("ticker") == ticker:
                fund = s.get("fundamentals", {})
                return fund.get("sector", "Unknown")
        return "Unknown"

    def _get_current_price(self, ticker: str, stocks_data: list[dict]) -> float:
        for s in stocks_data:
            if s.get("ticker") == ticker:
                ind = s.get("indicators", {})
                return float(ind.get("current_price", 0))
        return 0.0

    def _get_stock_metadata(self, ticker: str, stocks_data: list[dict]) -> dict[str, Any]:
        """Extract company metadata (industry, market_cap, description) for output."""
        for s in stocks_data:
            if s.get("ticker") == ticker:
                fund = s.get("fundamentals", {})
                summary = fund.get("business_summary", "")
                if len(summary) > 200:
                    summary = summary[:197] + "..."
                return {
                    "industry": fund.get("industry", "Unknown"),
                    "market_cap": fund.get("market_cap"),
                    "description": summary,
                }
        return {"industry": "Unknown", "market_cap": None, "description": ""}

    def _build_cycle_summary_payload(
        self,
        *,
        cycle_id: str,
        result: dict[str, Any],
        strategy_decisions: list[dict[str, Any]],
        opportunity_evaluations: list[dict[str, Any]],
        stocks_data: list[dict[str, Any]],
        per_ticker_news: dict[str, str],
        dry_run: bool,
    ) -> dict[str, Any]:
        """Build full cycle summary payload for notifications."""
        decisions = self._collect_decision_records(
            strategy_decisions=strategy_decisions,
            opportunity_evaluations=opportunity_evaluations,
            rejected_stocks=result.get("rejected_stocks", []),
            trades=result.get("trades", []),
            stocks_data=stocks_data,
            per_ticker_news=per_ticker_news,
        )

        rejected = result.get("rejected_stocks", [])
        queued = sum(1 for r in rejected if r.get("stage") == "opportunity_queue")
        filtered = sum(1 for r in rejected if r.get("stage") == "opportunity_filtered")

        return {
            "cycle_id": cycle_id,
            "status": result.get("status", "unknown"),
            "dry_run": dry_run,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "num_trades": len(result.get("trades", [])),
            "num_rejected": len(rejected),
            "counts": {
                "decisions": len(strategy_decisions),
                "trades": len(result.get("trades", [])),
                "rejected": len(rejected),
                "queued": queued,
                "filtered": filtered,
            },
            "decisions": decisions,
        }

    def _collect_decision_records(
        self,
        *,
        strategy_decisions: list[dict[str, Any]],
        opportunity_evaluations: list[dict[str, Any]],
        rejected_stocks: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        stocks_data: list[dict[str, Any]],
        per_ticker_news: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Build per-ticker decision records from cycle artifacts."""
        eval_by_key = {
            (str(e.get("ticker", "")), str(e.get("action", ""))): e
            for e in opportunity_evaluations
        }
        rejected_by_key = {
            (str(r.get("ticker", "")), str(r.get("action", ""))): r
            for r in rejected_stocks
        }
        trade_by_key = {
            (str(t.get("ticker", "")), str(t.get("action", ""))): t
            for t in trades
        }

        records: list[dict[str, Any]] = []
        for decision in strategy_decisions:
            ticker = str(decision.get("ticker", "")).upper()
            action = str(decision.get("action", "HOLD"))
            key = (ticker, action)
            evaluation = eval_by_key.get(key, {})
            rejected = rejected_by_key.get(key, {})
            trade = trade_by_key.get(key, {})
            moderation = evaluation.get("moderation", {}) or {}
            gpt_verdict = moderation.get("gpt4o_verdict") or {}
            gemini_verdict = moderation.get("gemini_verdict") or {}
            trade_exec = trade.get("execution", {}) or {}
            stop_loss = trade.get("stop_loss", {}) or {}
            metadata = self._get_stock_metadata(ticker, stocks_data)
            fundamentals = self._get_stock_fundamentals(ticker, stocks_data)
            yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
            news_excerpt = per_ticker_news.get(yf_ticker, decision.get("news_sentiment_summary", ""))

            stage = (
                rejected.get("stage")
                or evaluation.get("stage")
                or ("executed" if trade else "unrated")
            )
            stage_reason = rejected.get("reason") or evaluation.get("reason")

            # HOLD/QUEUED skip moderation and risk — show "not invoked" instead of null
            mod_consensus = evaluation.get("moderation_consensus") or rejected.get("moderation_consensus")
            risk_v = evaluation.get("risk_verdict") or rejected.get("risk_verdict")
            if stage in ("strategy_hold", "strategy_queued") and mod_consensus is None:
                mod_consensus = "not invoked"
            if stage in ("strategy_hold", "strategy_queued") and risk_v is None:
                risk_v = "not invoked"

            records.append({
                "ticker": ticker,
                "action": action,
                "stage": stage,
                "conviction": decision.get("conviction"),
                "target_allocation_pct": decision.get("target_allocation_pct"),
                "final_allocation_pct": evaluation.get("final_allocation_pct"),
                "moderation_consensus": mod_consensus,
                "risk_verdict": risk_v,
                "strategy_reasoning_excerpt": self._excerpt(decision.get("reasoning", ""), max_len=350),
                "gpt_reasoning_excerpt": self._excerpt(gpt_verdict.get("reasoning", ""), max_len=250),
                "gemini_assessment_excerpt": self._excerpt(gemini_verdict.get("assessment", ""), max_len=250),
                "gemini_growth_score": gemini_verdict.get("growth_score"),
                "gemini_risk_score": gemini_verdict.get("risk_score"),
                "gemini_confidence_score": gemini_verdict.get("confidence_score"),
                "industry": metadata.get("industry"),
                "market_cap": metadata.get("market_cap"),
                "description_excerpt": self._excerpt(metadata.get("description", ""), max_len=220),
                "trailing_pe": fundamentals.get("trailing_pe"),
                "pb_ratio": fundamentals.get("pb_ratio"),
                "roe": fundamentals.get("roe"),
                "profit_margin": fundamentals.get("profit_margin"),
                "debt_equity": fundamentals.get("debt_equity"),
                "earnings_growth": fundamentals.get("earnings_growth"),
                "news_excerpt": self._excerpt(news_excerpt, max_len=400),
                "execution_status": trade_exec.get("status"),
                "quantity": trade_exec.get("quantity"),
                "value_gbp": trade_exec.get("value_gbp"),
                "stop_loss_pct": decision.get("stop_loss_pct"),
                "stop_loss_status": stop_loss.get("status"),
                "stage_reason": stage_reason,
            })
            if rejected.get("uov_ewma") is not None:
                records[-1]["uov_ewma"] = rejected["uov_ewma"]
            if rejected.get("uov_z") is not None:
                records[-1]["uov_z"] = rejected["uov_z"]

        return records

    @staticmethod
    def _get_stock_fundamentals(ticker: str, stocks_data: list[dict[str, Any]]) -> dict[str, Any]:
        for stock in stocks_data:
            if stock.get("ticker") == ticker:
                return stock.get("fundamentals", {}) or {}
        return {}

    @staticmethod
    def _excerpt(text: Any, *, max_len: int) -> str:
        if text is None:
            return ""
        value = str(text).strip()
        if len(value) <= max_len:
            return value
        return value[: max_len - 3] + "..."

    @staticmethod
    def _normalize_decision_ticker(ticker: str, stocks_data: list[dict[str, Any]]) -> str:
        """Map raw strategy ticker symbols to instrument IDs used by execution.

        Claude may occasionally output a plain symbol (e.g. ``GILD``) instead of
        the expected Trading212 instrument ID (e.g. ``GILD_US_EQ``).
        """
        if not ticker:
            return ticker
        if ticker.endswith("_US_EQ") or ticker.endswith("_UK_EQ"):
            return ticker

        candidates: list[str] = []
        for stock in stocks_data:
            instrument_id = str(stock.get("ticker", "")).upper()
            if not instrument_id:
                continue
            if instrument_id == ticker:
                return instrument_id
            if instrument_id.startswith(f"{ticker}_"):
                candidates.append(instrument_id)

        if len(candidates) == 1:
            return candidates[0]

        # Fallback to instrument table mapping when stocks_data contains raw symbols.
        session = get_session()
        try:
            preferred = [f"{ticker}_US_EQ", f"{ticker}_UK_EQ"]
            rows = (
                session.query(Instrument.ticker)
                .filter(Instrument.ticker.in_(preferred))
                .all()
            )
            found = [str(r[0]).upper() for r in rows if r and r[0]]
            for instrument_id in preferred:
                if instrument_id in found:
                    return instrument_id
            if len(found) == 1:
                return found[0]
        except Exception:
            pass
        finally:
            session.close()

        return ticker

    def _get_sector_allocations(self, portfolio_data: dict) -> dict[str, float]:
        # Simplified — would need instrument metadata for full implementation
        return {}

    def _get_position_allocations(self, portfolio_data: dict) -> dict[str, float]:
        total = portfolio_data.get("total_value", 1)
        if total <= 0:
            return {}
        result: dict[str, float] = {}
        for pos in portfolio_data.get("positions", []):
            ticker = pos.get("ticker", "")
            qty = float(pos.get("quantity", 0))
            price = float(pos.get("currentPrice", 0))
            result[ticker] = (qty * price / total) * 100
        return result

    def _save_snapshot(self, portfolio_data: dict, state: str) -> None:
        """Save a portfolio snapshot."""
        session = get_session()
        try:
            session.add(PortfolioSnapshot(
                timestamp=datetime.now(timezone.utc),
                total_value_gbp=portfolio_data.get("total_value", 0),
                cash_gbp=portfolio_data.get("cash", 0),
                invested_gbp=portfolio_data.get("invested", 0),
                pnl_gbp=0.0,
                pnl_pct=portfolio_data.get("total_return_pct", 0),
                num_positions=portfolio_data.get("num_positions", 0),
                positions_json=json.dumps(portfolio_data.get("positions", []), default=str),
                state=state,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            session.rollback()
        finally:
            session.close()

    def get_status(self) -> dict[str, Any]:
        """Get current system status summary."""
        state = self.state_machine.get_state()
        cost = get_cost_summary(days=1)
        return {
            "system_state": state,
            "cost_today": cost,
            "degradation": get_degradation_level().value,
        }

    def force_sell(self, ticker: str) -> dict[str, Any]:
        """Force sell a specific position."""
        logger.info(f"Force selling {ticker}")
        try:
            position = self.t212_client.get_position(ticker)
            qty = float(position.get("quantity", 0))
            if qty <= 0:
                return {"status": "no_position", "ticker": ticker}

            if self.dry_run:
                return {"status": "dry_run", "ticker": ticker, "quantity": qty}

            result = self.t212_client.place_market_order(ticker, -qty)
            return {"status": "sold", "ticker": ticker, "quantity": qty, "result": result}
        except Exception as e:
            logger.error(f"Force sell failed for {ticker}: {e}")
            return {"status": "error", "ticker": ticker, "error": str(e)}

    def close(self) -> None:
        """Clean up resources."""
        self.data_fetcher.close()
        if self._t212_client:
            self._t212_client.close()


# --- CLI ---

def _get_performance_summary() -> dict[str, Any]:
    """Load latest performance metrics and cost summary for CLI."""
    from src.agents.reporting.performance_tracker import update_performance_metrics

    session = get_session()
    try:
        update_performance_metrics(session=session)
        latest = (
            session.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )
        perf = (
            session.query(PerformanceMetric)
            .order_by(PerformanceMetric.snapshot_date.desc())
            .first()
        )
        cost = get_cost_summary(days=1)
        return {
            "portfolio": {
                "total_value_gbp": latest.total_value_gbp if latest else None,
                "cash_gbp": latest.cash_gbp if latest else None,
                "num_positions": latest.num_positions if latest else None,
                "state": latest.state if latest else None,
                "timestamp": latest.timestamp.isoformat() if latest else None,
            },
            "metrics": {
                "sharpe_30d": perf.sharpe_30d if perf else None,
                "sharpe_60d": perf.sharpe_60d if perf else None,
                "sharpe_90d": perf.sharpe_90d if perf else None,
                "sortino_30d": perf.sortino_30d if perf else None,
                "max_drawdown_pct": perf.max_drawdown_pct if perf else None,
                "calmar_ratio": perf.calmar_ratio if perf else None,
                "win_rate_momentum": perf.win_rate_momentum if perf else None,
                "win_rate_mean_reversion": perf.win_rate_mean_reversion if perf else None,
                "win_rate_factor": perf.win_rate_factor if perf else None,
                "alpha_vs_spy_pct": perf.alpha_vs_spy_pct if perf else None,
                "num_trades": perf.num_trades if perf else None,
            },
            "cost_today": cost,
        }
    finally:
        session.close()


def _get_dashboard_summary() -> dict[str, Any]:
    """Dashboard: portfolio, performance, costs, active positions."""
    summary = _get_performance_summary()
    session = get_session()
    try:
        latest = (
            session.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )
        positions: list[dict[str, Any]] = []
        if latest and latest.positions_json:
            positions = json.loads(latest.positions_json)
        summary["active_positions"] = [
            {"ticker": p.get("ticker"), "quantity": p.get("quantity"), "value_gbp": p.get("value", 0)}
            for p in positions[:20]
        ]
        return summary
    finally:
        session.close()


@click.command()
@click.option("--dry-run", is_flag=True, help="Run without executing trades")
@click.option("--uov-diagnostic", is_flag=True, help="Run with UOV in shadow mode and emit UOV scores for calibration")
@click.option("--force-sell", "force_sell_ticker", default=None, help="Force sell a position")
@click.option("--pause", is_flag=True, help="Pause the system")
@click.option("--resume", "do_resume", is_flag=True, help="Resume the system")
@click.option("--report", is_flag=True, help="Generate a status report")
@click.option("--status", is_flag=True, help="Show system status")
@click.option("--performance", is_flag=True, help="Show performance metrics summary")
@click.option("--dashboard", is_flag=True, help="Show dashboard: portfolio, metrics, costs, positions")
def main(
    dry_run: bool,
    uov_diagnostic: bool,
    force_sell_ticker: str | None,
    pause: bool,
    do_resume: bool,
    report: bool,
    status: bool,
    performance: bool,
    dashboard: bool,
) -> None:
    """Investment Agent Orchestrator."""
    orchestrator = Orchestrator(dry_run=dry_run, uov_diagnostic=uov_diagnostic)

    try:
        if status:
            s = orchestrator.get_status()
            click.echo(json.dumps(s, indent=2, default=str))
            return

        if performance:
            click.echo(json.dumps(_get_performance_summary(), indent=2, default=str))
            return

        if dashboard:
            click.echo(json.dumps(_get_dashboard_summary(), indent=2, default=str))
            return

        if pause:
            orchestrator.state_machine.pause()
            click.echo("System PAUSED")
            return

        if do_resume:
            orchestrator.state_machine.resume()
            click.echo("System RESUMED")
            return

        if force_sell_ticker:
            result = orchestrator.force_sell(force_sell_ticker)
            click.echo(json.dumps(result, indent=2, default=str))
            return

        if report:
            # Import here to avoid circular imports
            from src.agents.reporting.daily_report import generate_daily_report
            path = generate_daily_report()
            click.echo(f"Report generated: {path}")
            return

        # Run a full cycle
        result = orchestrator.run_cycle()
        if uov_diagnostic and result.get("opportunity_ranking"):
            click.echo("\n--- UOV Diagnostic (opportunity_ranking) ---", err=True)
            for s in sorted(result["opportunity_ranking"], key=lambda x: float(x.get("uov_ewma", 0)), reverse=True):
                click.echo(
                    f"  {s.get('ticker', 'N/A')} {s.get('action', 'N/A')} | "
                    f"uov_ewma={s.get('uov_ewma', 'N/A')} uov_z={s.get('uov_z', 'N/A')} | "
                    f"stage={s.get('stage', 'N/A')} tradable={s.get('is_tradable', False)}",
                    err=True,
                )
            if result.get("queued_candidates"):
                click.echo("\nQueued candidates:", err=True)
                for q in result["queued_candidates"]:
                    click.echo(f"  {q.get('ticker')} queued_cycles={q.get('queued_cycles')} uov_ewma={q.get('uov_ewma')}", err=True)
            click.echo("---\n", err=True)
        click.echo(json.dumps(result, indent=2, default=str))

    finally:
        orchestrator.close()


if __name__ == "__main__":
    main()
