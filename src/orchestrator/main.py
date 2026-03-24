"""Orchestrator — main control loop for the investment agent.

Runs every 12 hours during market hours (configurable).
Sequence: Data -> Strategy -> Moderation -> Risk -> Execution -> Journal
"""

import json
import signal
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import click

from src.agents.execution.order_manager import OrderManager
from src.agents.execution.stop_loss_manager import StopLossManager
from src.agents.execution.t212_client import T212Client, calculate_quantity
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
from src.agents.risk.risk_parity import RiskParitySizer
from src.agents.risk.risk_manager import RiskManager
from src.agents.strategy.engine import StrategyEngine
from src.data.database import get_session
from src.data.models import Base, Instrument, OpportunityQueue, PerformanceMetric, PortfolioSnapshot
from src.orchestrator.state_machine import StateMachine
from src.runtime import RuntimeLockHeldError, acquire_runtime_lock
from src.utils.config import get_settings
from src.utils.cost_tracker import DegradationLevel, get_cost_summary, get_degradation_level
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

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
        self.risk_parity_sizer = RiskParitySizer()
        self.opportunity_scorer = OpportunityScorer()
        self.opportunity_optimizer = OpportunityOptimizer()

        self._t212_client: T212Client | None = None
        self._order_manager: OrderManager | None = None
        self._stop_loss_manager: StopLossManager | None = None
        self._last_screened_candidate_count = 0
        self._last_screening_skipped_no_data = 0

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

        result: dict[str, Any] = {
            "cycle_id": cycle_id,
            "trades": [],
            "rejected_stocks": [],
            "errors": [],
            "opportunity_ranking": [],
            "queued_candidates": [],
            "swap_candidates": [],
        }
        cycle_lock = None
        try:
            cycle_lock = acquire_runtime_lock(
                "orchestrator-cycle",
                metadata={
                    "cycle_id": cycle_id,
                    "dry_run": self.dry_run,
                    "scheduled_cycle_id": scheduled_cycle_id,
                },
            )
        except RuntimeLockHeldError as exc:
            logger.warning(
                "Skipping cycle %s because another cycle is already running (lock=%s owner=%s)",
                cycle_id,
                exc.lock_path,
                exc.details.get("pid"),
            )
            result["status"] = "skipped_locked"
            result["lock_path"] = str(exc.lock_path)
            if exc.details:
                result["lock_details"] = exc.details
            return result

        logger.info(f"Starting cycle {cycle_id} (dry_run={self.dry_run})")
        self._last_screened_candidate_count = 0
        self._last_screening_skipped_no_data = 0

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
                    try:
                        run = Run(
                            cycle_id=cycle_id,
                            run_type="manual" if not self.dry_run else "dry_run",
                            started_at=cycle_start_time,
                            status="running",
                        )
                        session.add(run)
                        session.commit()
                        logger.debug(f"Created Run record for cycle {cycle_id}")
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as e:
                    logger.debug(f"Failed to create Run record (fail-open): {e}", exc_info=True)
            except Exception:
                pass  # Fail-open

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
            result["stocks_reviewed"] = len(strategy_decisions)
            result["stocks_screened"] = self._last_screened_candidate_count
            result["stocks_skipped_no_data"] = self._last_screening_skipped_no_data
            rejected = result["rejected_stocks"]
            result["num_rejected"] = len(rejected)
            result["rejected_by_action"] = dict(Counter(r.get("action", "HOLD") for r in rejected))
            result["cost_summary"] = get_cost_summary(days=1)

            # P2-3: Decision chain integrity check — detect orphaned decisions
            traded_tickers = {t.get("ticker") for t in result["trades"] if t.get("ticker")}
            rejected_tickers = {r.get("ticker") for r in rejected if r.get("ticker")}
            accounted = traded_tickers | rejected_tickers
            decided_tickers = {str(d.get("ticker", "")).strip().upper() for d in strategy_decisions if d.get("ticker")}
            orphaned_decisions = decided_tickers - accounted
            if orphaned_decisions:
                logger.warning(
                    f"Decision chain integrity: {len(orphaned_decisions)} strategy decisions "
                    f"have no corresponding trade or rejection record: {orphaned_decisions}"
                )
                result["orphaned_decisions"] = list(orphaned_decisions)

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
                            "stocks_screened": result["stocks_screened"],
                            "stocks_reviewed": result["stocks_reviewed"],
                            "num_trades": result["num_trades"],
                            "num_rejected": result["num_rejected"],
                        },
                    )
                    # Update run record (session leak fix H-6)
                    try:
                        from dashboard.backend.app.database import Run
                        session = get_session()
                        try:
                            run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                            if run:
                                run.completed_at = cycle_end_time
                                run.status = status
                                run.summary_json = {
                                    "stocks_screened": result["stocks_screened"],
                                    "stocks_reviewed": result["stocks_reviewed"],
                                    "decisions_made": result["stocks_reviewed"],
                                    "num_trades": result["num_trades"],
                                    "num_rejected": result["num_rejected"],
                                    "duration_seconds": duration_seconds,
                                }
                                session.commit()
                                logger.debug(f"Updated Run record for cycle {cycle_id}")
                            else:
                                logger.debug(f"Run record not found for cycle {cycle_id}, creating new one")
                                run = Run(
                                    cycle_id=cycle_id,
                                    run_type="scheduled" if scheduled_cycle_id else ("manual" if not self.dry_run else "dry_run"),
                                    started_at=cycle_start_time,
                                    completed_at=cycle_end_time,
                                    status=status,
                                    summary_json={
                                        "stocks_screened": result["stocks_screened"],
                                        "stocks_reviewed": result["stocks_reviewed"],
                                        "decisions_made": result["stocks_reviewed"],
                                        "num_trades": result["num_trades"],
                                        "num_rejected": result["num_rejected"],
                                        "duration_seconds": duration_seconds,
                                    },
                                )
                                session.add(run)
                                session.commit()
                        except Exception:
                            session.rollback()
                            raise
                        finally:
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

        # Cycle-level timeout (audit fix M-7) — prevents indefinite hangs from LLM calls
        cycle_timeout = self.settings.cycle_timeout_seconds
        _prev_alarm_handler = None
        try:
            if hasattr(signal, "SIGALRM") and signal.getsignal(signal.SIGALRM) is not signal.SIG_IGN:
                def _timeout_handler(signum: int, frame: Any) -> None:
                    raise TimeoutError(f"Cycle {cycle_id} exceeded {cycle_timeout}s timeout")
                _prev_alarm_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(cycle_timeout)
                logger.debug(f"Cycle timeout set: {cycle_timeout}s")
        except (ValueError, OSError):
            pass  # Not in main thread or signal unavailable — skip timeout

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
                # Fetch portfolio before liquidation for meaningful notifications (audit fix M-11)
                try:
                    portfolio_data = self._get_portfolio_state()
                    result["portfolio_at_halt"] = {
                        "total_value": portfolio_data.get("total_value"),
                        "cash": portfolio_data.get("cash"),
                        "num_positions": portfolio_data.get("num_positions"),
                    }
                except Exception as port_err:
                    logger.warning(f"Could not fetch portfolio data during HALT: {port_err}")
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
            # Track cash committed by BUYs within this cycle to prevent over-allocation
            # (audit fix H-2: stale portfolio data)
            committed_cash = 0.0

            # Sync order status from T212 (pending -> filled)
            if not self.dry_run:
                try:
                    self.order_manager.sync_order_status_from_t212()
                except Exception as sync_err:
                    logger.warning(f"Order status sync skipped: {sync_err}")

            # Reconcile orphaned EXECUTING queue entries (P2-6 crash recovery)
            if self.settings.opportunity_enabled:
                try:
                    orphaned = self.opportunity_optimizer.reconcile_orphaned_executing()
                    if orphaned:
                        logger.info(f"Reconciled {len(orphaned)} orphaned EXECUTING queue entries: {orphaned}")
                except Exception as recon_err:
                    logger.warning(f"Queue reconciliation skipped: {recon_err}")

            # Update peak and check drawdown
            practice_skips_state_machine = self.settings.is_practice_account
            if not self.dry_run and not practice_skips_state_machine:
                # Live + real account: full state machine (CAUTIOUS/HALTED)
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
                # Dry-run or practice account: log drawdown but stay ACTIVE (no state transitions)
                state_info = self.state_machine.get_state()
                peak_value = state_info.get("peak_portfolio_value", current_value)
                drawdown_pct = ((peak_value - current_value) / peak_value * 100) if peak_value > 0 else 0
                drawdown_state = self.risk_manager.get_drawdown_state(current_value, peak_value)
                if drawdown_state != "ACTIVE":
                    reason = "dry-run" if self.dry_run else "practice account"
                    logger.info(
                        f"{reason.capitalize()}: drawdown {drawdown_pct:.1f}% would trigger {drawdown_state}, "
                        f"staying ACTIVE (state machine relaxed)"
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

            existing_tickers = {t for p in portfolio_data.get("positions", []) if (t := self._ticker_from_position(p))}

            # Get data for current positions AND screen universe for new candidates
            stocks_data = self._fetch_stocks_data(
                current_positions=portfolio_data.get("positions", []),
                exclude_tickers=existing_tickers,
                system_state=current_state,
                cycle_id=cycle_id,
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
                    yf_ticker = t212_to_yf(ticker)
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
                    yf_tickers = [t212_to_yf(t) for t in active_review_tickers]
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
                all_yf_tickers = [t212_to_yf(t) for t in active_review_tickers]
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

            # Inject persisted proactive macro state when available (US-4.5 foundation)
            macro_state = macro.get("macro_state", {})
            if macro_state.get("enabled"):
                news_parts.append("\n### Proactive Macro State")
                news_parts.append(
                    "Regime: "
                    f"{macro_state.get('regime', 'NEUTRAL')} | "
                    f"Confidence: {float(macro_state.get('confidence_score', 0.0)):.2f}"
                )
                top_signals = macro_state.get("top_signals", [])[:3]
                if top_signals:
                    news_parts.append("Top signals:")
                    for sig in top_signals:
                        news_parts.append(
                            f"- [{sig.get('signal_type', 'macro')}] "
                            f"{sig.get('signal_text', '')}"
                        )
                if macro_state.get("sector_summary"):
                    news_parts.append("Persisted sector summary:")
                    news_parts.append(str(macro_state["sector_summary"]))
                if macro_state.get("economic_highlights"):
                    news_parts.append("Persisted economic highlights:")
                    news_parts.append(str(macro_state["economic_highlights"]))
                action_plan = macro_state.get("action_plan", {})
                if action_plan:
                    news_parts.append("Macro action plan:")
                    if action_plan.get("summary"):
                        news_parts.append(str(action_plan["summary"]))
                    for implication in action_plan.get("sector_implications", [])[:3]:
                        news_parts.append(
                            f"- {implication.get('sector', 'Market')}: "
                            f"{implication.get('bias', 'mixed')} — "
                            f"{implication.get('rationale', '')}"
                        )

            analyst_summary = json.dumps(analyst_data_map, indent=2, default=str)[:3000]
            news_summary = "\n".join(news_parts)[:3000] if news_parts else "News sentiment data unavailable."
            macro_context_summary = "No persisted proactive macro state available."
            if macro_state.get("enabled"):
                macro_context_lines = [
                    f"Regime: {macro_state.get('regime', 'NEUTRAL')}",
                    f"Confidence: {float(macro_state.get('confidence_score', 0.0)):.2f}",
                ]
                if top_signals:
                    macro_context_lines.append(
                        "Top signals: "
                        + " | ".join(sig.get("signal_text", "") for sig in top_signals)
                    )
                action_plan = macro_state.get("action_plan", {})
                if action_plan.get("summary"):
                    macro_context_lines.append(f"Action plan: {action_plan['summary']}")
                macro_context_summary = "\n".join(macro_context_lines)[:1500]

            # Build company profiles for top candidates
            all_stock_tickers = [s.get("ticker", "") for s in stocks_data if s.get("ticker")][:self.settings.max_candidates]
            company_profiles = self._build_company_profiles(stocks_data, all_stock_tickers)
            uov_swap_context = self.opportunity_scorer.build_swap_context(existing_tickers)

            # Shared research executor for strategy + moderation (pipeline-wide budget)
            research_executor = None
            if self.settings.research_enabled:
                from src.agents.research import ResearchExecutor
                research_executor = ResearchExecutor(cycle_id=cycle_id)

            # Build position P&L summary and strategy performance for the prompt
            position_pnl = self._build_position_pnl_summary(portfolio_data)
            strategy_performance = self._build_strategy_performance_summary()

            # Claude synthesis
            portfolio_state_str = json.dumps(portfolio_data, indent=2, default=str)[:2000]
            strategy_result = self.strategy_engine.synthesize_with_claude(
                sub_strategy_results=sub_results,
                portfolio_state=portfolio_state_str,
                market_regime=market_regime,
                analyst_data=analyst_summary,
                news_sentiment=news_summary,
                macro_context=macro_context_summary,
                company_profiles=company_profiles,
                system_state=current_state,
                vix=vix,
                cash_pct=cash_pct,
                num_positions=len(existing_tickers),
                cycle_id=cycle_id,
                uov_swap_context=uov_swap_context,
                research_executor=research_executor,
                position_pnl=position_pnl,
                strategy_performance=strategy_performance,
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

            # Compute portfolio return series for correlation check (audit fix H-3)
            portfolio_returns = self._get_portfolio_returns(
                portfolio_data.get("positions", []), stocks_data,
            )

            # --- STEP 5: Moderation -> Risk -> (Deferred BUY Execution) ---
            pending_buys: list[dict[str, Any]] = []
            projected_num_positions = len(existing_tickers)

            # Deduplicate decisions by ticker — keep first occurrence (audit fix)
            seen_tickers: set[str] = set()
            deduped_decisions: list[dict[str, Any]] = []
            for d in decisions:
                t = str(d.get("ticker", "")).strip().upper()
                if t and t in seen_tickers:
                    logger.warning(f"Duplicate decision for {t} — keeping first, dropping duplicate")
                    continue
                if t:
                    seen_tickers.add(t)
                deduped_decisions.append(d)
            if len(deduped_decisions) < len(decisions):
                logger.info(f"Deduplicated {len(decisions)} -> {len(deduped_decisions)} decisions")
            decisions = deduped_decisions

            for decision in decisions:
                raw_ticker = str(decision.get("ticker", "")).strip().upper()
                ticker = self._normalize_decision_ticker(raw_ticker, stocks_data)
                if raw_ticker and ticker != raw_ticker:
                    logger.warning(f"Normalized strategy ticker '{raw_ticker}' -> '{ticker}'")
                    decision["ticker"] = ticker

                raw_conviction = decision.get("conviction", 0)
                conviction = max(0, min(100, int(raw_conviction) if raw_conviction else 0))
                if conviction != raw_conviction:
                    logger.warning(f"Clamped conviction for {ticker}: {raw_conviction} -> {conviction}")
                    decision["conviction"] = conviction

                raw_alloc = decision.get("target_allocation_pct", 0)
                max_alloc = self.settings.max_single_stock_pct
                target_alloc = max(0.0, min(float(max_alloc), float(raw_alloc) if raw_alloc else 0.0))
                if target_alloc != raw_alloc:
                    logger.warning(f"Clamped target_allocation_pct for {ticker}: {raw_alloc} -> {target_alloc}")
                decision["target_allocation_pct"] = target_alloc
                if decision.get("action") == "BUY":
                    decision["claude_target_allocation_pct"] = target_alloc

            risk_parity_rejections: list[dict[str, Any]] = []
            if self.settings.risk_parity_enabled:
                decisions, risk_parity_rejections = self._apply_risk_parity_sizing(
                    decisions=decisions,
                    stocks_data=stocks_data,
                    portfolio_data=portfolio_data,
                    cash_pct=cash_pct,
                )
            parity_logged_decisions = decisions + [
                rejected["decision"] for rejected in risk_parity_rejections if rejected.get("decision")
            ]
            if hasattr(self.strategy_engine, "apply_risk_parity_metadata"):
                self.strategy_engine.apply_risk_parity_metadata(cycle_id, parity_logged_decisions)
            strategy_decisions = decisions

            for rejected in risk_parity_rejections:
                result["rejected_stocks"].append(rejected)
                opportunity_evaluations.append({
                    "ticker": rejected["ticker"],
                    "action": rejected["action"],
                    "stage": rejected["stage"],
                    "decision": rejected.get("decision"),
                    "reason": rejected["reason"],
                    "moderation_consensus": "not invoked",
                    "risk_verdict": "not invoked",
                    "final_allocation_pct": None,
                })

            for decision in decisions:
                ticker = str(decision.get("ticker", "")).strip().upper()
                action = decision.get("action", "HOLD")
                conviction = int(decision.get("conviction", 0) or 0)
                target_alloc = float(decision.get("target_allocation_pct", 0.0) or 0.0)

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
                yf_ticker_for_news = t212_to_yf(ticker)
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
                    portfolio_returns=portfolio_returns,
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
                    conviction=conviction,
                    is_losing_position=self._is_losing_position(ticker, portfolio_data),
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

                # Apply moderator modifications — use most conservative allocation cap (audit fix C-1)
                mod_modifications = mod_result.modifications
                if mod_modifications and mod_modifications.get("target_allocation_pct"):
                    mod_cap = float(mod_modifications["target_allocation_pct"])
                    if mod_cap < final_alloc:
                        logger.info(f"MODIFY cap applied for {ticker}: {final_alloc:.1f}% -> {mod_cap:.1f}%")
                        final_alloc = mod_cap

                # CAUTION consensus: reduce allocation by 25% (audit fix C-2)
                if mod_result.consensus == "CAUTION" and action == "BUY":
                    caution_alloc = round(final_alloc * 0.75, 2)
                    logger.info(
                        f"CAUTION allocation reduction for {ticker}: {final_alloc:.1f}% -> {caution_alloc:.1f}%"
                    )
                    final_alloc = caution_alloc

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
                    portfolio_data=portfolio_data,
                )
                if trade_entry:
                    result["trades"].append(trade_entry)
                    if action == "SELL" and trade_entry.get("execution", {}).get("status") in ("filled", "dry_run"):
                        projected_num_positions = max(0, projected_num_positions - 1)

            # Re-query portfolio before BUY phase (P2-4: avoid stale data after SELL/REDUCE)
            sells_executed = any(
                t.get("action") in ("SELL", "REDUCE")
                and t.get("execution", {}).get("status") in ("filled", "dry_run")
                for t in result.get("trades", [])
            )
            if sells_executed and pending_buys and not self.dry_run:
                try:
                    refreshed = self._get_portfolio_state()
                    current_value = refreshed["total_value"]
                    cash_gbp = refreshed["cash"]
                    cash_pct = (cash_gbp / current_value * 100) if current_value > 0 else 100
                    committed_cash = 0.0  # Reset — fresh portfolio state
                    portfolio_data = refreshed
                    logger.info(
                        f"Portfolio refreshed before BUY phase: cash=£{cash_gbp:.2f} "
                        f"({cash_pct:.1f}%), total=£{current_value:.2f}"
                    )
                except Exception as refresh_err:
                    logger.warning(f"Portfolio refresh before BUY skipped: {refresh_err}")

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
                    if trade_value < self.settings.min_order_value_gbp:
                        logger.info(
                            f"Limit BUY skipped: trade value £{trade_value:.2f} below minimum"
                        )
                        continue
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
                        # Track committed cash for limit BUYs (audit fix H-2)
                        if limit_result.get("status") in ("placed", "pending", "dry_run"):
                            committed_cash += trade_value
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

                buy_alloc = float(pending.get("final_allocation_pct", 0.0))
                # Check remaining cash before BUY (audit fix H-2)
                available_cash = cash_gbp - committed_cash
                available_cash_pct = (available_cash / current_value * 100) if current_value > 0 else 0
                buy_value = current_value * buy_alloc / 100
                cash_floor = self.settings.cash_floor_pct
                if available_cash_pct - (buy_value / current_value * 100 if current_value > 0 else 0) < cash_floor:
                    logger.info(
                        f"BUY {ticker} skipped: would breach cash floor "
                        f"(available={available_cash_pct:.1f}%, buy={buy_alloc:.1f}%, floor={cash_floor}%)"
                    )
                    result["rejected_stocks"].append({
                        "ticker": ticker,
                        "action": "BUY",
                        "stage": "cash_floor_guard",
                        "reason": f"Insufficient cash after prior BUYs (available {available_cash_pct:.1f}%)",
                        "conviction": decision.get("conviction", 0),
                        **self._get_stock_metadata(ticker, stocks_data),
                    })
                    continue

                trade_entry = self._execute_trade(
                    cycle_id=cycle_id,
                    decision=decision,
                    action="BUY",
                    ticker=ticker,
                    final_alloc=buy_alloc,
                    current_value=current_value,
                    cash_gbp=cash_gbp - committed_cash,
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
                    portfolio_data=portfolio_data,
                )
                if trade_entry:
                    result["trades"].append(trade_entry)
                    # Track committed cash so subsequent BUYs see reduced availability
                    exec_result = trade_entry.get("execution", {})
                    if exec_result.get("status") in ("filled", "pending", "dry_run"):
                        committed_cash += exec_result.get("value_gbp", buy_value)

            # Dequeue executed BUY tickers from opportunity queue (P2-6)
            if self.settings.opportunity_enabled:
                executed_buy_tickers = [
                    t.get("ticker")
                    for t in result.get("trades", [])
                    if t.get("action") == "BUY"
                    and t.get("execution", {}).get("status") in ("filled", "pending", "dry_run")
                ]
                if executed_buy_tickers:
                    try:
                        self.opportunity_optimizer.dequeue_executed(executed_buy_tickers)
                    except Exception as dq_err:
                        logger.warning(f"Failed to dequeue executed tickers: {dq_err}")

            # --- STEP 7: Intelligent order management (stop-loss reassessment) ---
            if self.settings.order_management_enabled:
                try:
                    current_positions = portfolio_data.get("positions", [])
                    all_adjustments: list[dict[str, Any]] = []

                    # Place missing stops for positions without one
                    missing_results = self.stop_loss_manager.place_missing_stops(
                        positions=current_positions,
                        stocks_data=stocks_data,
                        cycle_id=cycle_id,
                    )
                    all_adjustments.extend(missing_results)

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
            # Wrap notification in try/except so it never replaces the original
            # exception (audit fix M-8)
            try:
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
            except Exception as notify_err:
                logger.error(f"Failed to emit critical failure notification: {notify_err}")
            try:
                _emit_cycle_summary()
            except Exception as summary_err:
                logger.error(f"Failed to emit cycle summary after failure: {summary_err}")
            raise
        finally:
            # Cancel cycle timeout alarm (audit fix M-7)
            try:
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
                    if _prev_alarm_handler is not None:
                        signal.signal(signal.SIGALRM, _prev_alarm_handler)
            except (ValueError, OSError):
                pass
            if cycle_lock is not None:
                cycle_lock.release()

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
                cash = float(cash_data.get("free") or cash_data.get("availableToTrade") or 0)
                reserved = float(
                    cash_data.get("reservedForOrders") or cash_data.get("blocked") or cash_data.get("reserved") or 0
                )
            else:
                cash = float(cash_data)
                reserved = 0.0
            invested = float((summary.get("investments") or {}).get("currentValue", 0) or 0)
            if invested <= 0:
                invested = sum(
                    float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
                    for p in positions
                )
            total_value = cash + invested + reserved

        # Cash for allocation logic: free/available only
        if isinstance(cash_data, dict):
            cash = float(cash_data.get("free") or cash_data.get("availableToTrade") or 0)
        else:
            cash = float(cash_data)
        invested = float((summary.get("investments") or {}).get("currentValue", 0) or 0)
        if invested <= 0:
            invested = sum(
                float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
                for p in positions
            )

        # Compute daily P&L from most recent portfolio snapshot (audit fix H-4)
        daily_pnl_pct = 0.0
        try:
            from src.data.models import PortfolioSnapshot
            snap_session = get_session()
            try:
                yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
                latest_snap = (
                    snap_session.query(PortfolioSnapshot)
                    .filter(PortfolioSnapshot.timestamp <= yesterday)
                    .order_by(PortfolioSnapshot.timestamp.desc())
                    .first()
                )
                if latest_snap and latest_snap.total_value_gbp > 0:
                    daily_pnl_pct = ((total_value - latest_snap.total_value_gbp)
                                     / latest_snap.total_value_gbp * 100)
                    logger.debug(
                        f"Daily P&L: {daily_pnl_pct:+.2f}% "
                        f"(current={total_value:.0f}, snap={latest_snap.total_value_gbp:.0f})"
                    )
            finally:
                snap_session.close()
        except Exception as e:
            logger.debug(f"Could not compute daily P&L (using 0.0): {e}")

        return {
            "cash": cash,
            "total_value": total_value,
            "invested": invested,
            "positions": positions,
            "num_positions": len(positions),
            "daily_pnl_pct": daily_pnl_pct,
            "total_return_pct": ((total_value / 10000) - 1) * 100 if total_value > 0 else 0,
            "alpha_pct": 0.0,
        }

    def _fetch_stocks_data(
        self,
        current_positions: list[dict],
        exclude_tickers: set[str] | None = None,
        system_state: str = "ACTIVE",
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch analysis data for current positions + screened universe candidates.

        Two phases:
        1. Analyze all current positions (always).
        2. Screen the instrument universe for new candidates using sector-balanced,
           market-cap-tiered sampling (always run; Risk blocks new BUYs in CAUTIOUS).

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
            ticker = self._ticker_from_position(pos)
            if not ticker:
                continue
            yf_ticker = t212_to_yf(ticker)
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

        # Phase 2: Screen universe for new candidates (always; Risk blocks new BUYs in CAUTIOUS)
        all_exclude = analyzed_tickers | (exclude_tickers or set())
        try:
            candidates = self.data_fetcher.get_screened_universe(
                exclude_tickers=all_exclude,
                positions_count=len(current_positions),
                cycle_id=cycle_id,
            )
            self._last_screened_candidate_count = len(candidates)
            self.data_fetcher.mark_instruments_screened(
                [c["ticker"] for c in candidates],
            )
            logger.info(f"Screening {len(candidates)} universe candidates...")
            skipped_no_data = 0
            for candidate in candidates:
                c_ticker = candidate["ticker"]
                yf_ticker = t212_to_yf(c_ticker)
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
                self._last_screening_skipped_no_data = skipped_no_data
                logger.info(f"Skipped {skipped_no_data} candidates with no OHLCV data")
        except Exception as e:
            logger.warning(f"Universe screening failed: {e}")

        # Phase 3: Re-evaluate queued tickers (bypass cooldown so they can reach 2nd cycle)
        if self.settings.opportunity_enabled:
            try:
                q_session = get_session()
                try:
                    queued_rows = q_session.query(OpportunityQueue).all()
                finally:
                    q_session.close()
                queued_tickers = [r.ticker for r in queued_rows if r.ticker and r.ticker not in analyzed_tickers]
                added_queued = 0
                for ticker in queued_tickers:
                    yf_ticker = t212_to_yf(ticker)
                    try:
                        cached = self.data_fetcher.get_cached_data(yf_ticker, cache_key)
                        if cached:
                            if cached.get("indicators", {}).get("error"):
                                continue
                            cached["ticker"] = ticker
                            stocks_data.append(cached)
                        else:
                            data = fetch_fn(yf_ticker)
                            data["ticker"] = ticker
                            if data.get("indicators", {}).get("error"):
                                continue
                            stocks_data.append(data)
                            self.data_fetcher.enrich_instrument_metadata(
                                ticker, data.get("fundamentals", {}),
                            )
                        analyzed_tickers.add(ticker)
                        added_queued += 1
                    except Exception as e:
                        logger.debug(f"Failed to fetch queued ticker {ticker}: {e}")
                if added_queued:
                    logger.info(f"Re-evaluating {added_queued} queued tickers for promotion")
            except Exception as e:
                logger.warning(f"Queued ticker re-evaluation failed: {e}")

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
        portfolio_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Execute an approved trade and generate journal + stop-loss where relevant."""
        current_price = self._get_current_price(ticker, stocks_data)
        price_gbp = self._compute_fx_price_gbp(current_price, ticker, portfolio_data)

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

        min_order = self.settings.min_order_value_gbp
        execution_note: str | None = None
        trade_value: float

        if action == "BUY":
            portfolio = portfolio_data or {}
            allocs = self._get_position_allocations(portfolio)
            current_position_pct = allocs.get(ticker, 0.0)
            current_position_value = (current_position_pct / 100) * current_value
            target_position_value = current_value * final_alloc / 100
            trade_value = max(0.0, target_position_value - current_position_value)
            if trade_value <= 0:
                logger.info(
                    f"BUY skipped for {ticker}: target {final_alloc:.2f}% already met "
                    f"(current {current_position_pct:.2f}%)"
                )
                self.notification_service.emit_trade_execution_result(
                    cycle_id=cycle_id,
                    payload={
                        "cycle_id": cycle_id,
                        "dry_run": self.dry_run,
                        "ticker": ticker,
                        "action": action,
                        "execution_status": "skipped",
                        "quantity": 0,
                        "price": current_price,
                        "value_gbp": trade_value,
                        "stop_loss_pct": decision.get("stop_loss_pct", 0),
                        "stop_loss_status": None,
                        "error_message": "target_already_met",
                        "reasoning_summary": decision.get("reasoning", ""),
                        "target_allocation_pct": final_alloc,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return None
            if trade_value < min_order:
                logger.info(f"BUY skipped: trade value £{trade_value:.2f} below minimum £{min_order}")
                self.notification_service.emit_trade_execution_result(
                    cycle_id=cycle_id,
                    payload={
                        "cycle_id": cycle_id,
                        "dry_run": self.dry_run,
                        "ticker": ticker,
                        "action": action,
                        "execution_status": "skipped",
                        "quantity": 0,
                        "price": current_price,
                        "value_gbp": trade_value,
                        "stop_loss_pct": decision.get("stop_loss_pct", 0),
                        "stop_loss_status": None,
                        "error_message": "below_min_order_value",
                        "reasoning_summary": decision.get("reasoning", ""),
                        "target_allocation_pct": final_alloc,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return None
        else:
            # REDUCE or SELL: compute reduction amount and apply tiers
            portfolio = portfolio_data or {}
            allocs = self._get_position_allocations(portfolio)
            current_position_pct = allocs.get(ticker, 0.0)
            current_position_value = (current_position_pct / 100) * current_value
            target_position_value = current_value * final_alloc / 100
            reduction_amount = current_position_value - target_position_value

            if action == "SELL":
                reduction_pct = 100.0
                reduction_amount = current_position_value
                trade_value = current_position_value
            else:
                reduction_pct = (
                    (reduction_amount / current_position_value * 100)
                    if current_position_value > 0
                    else 0.0
                )
                tiers = self.settings.reduce_tiers_pct
                if tiers:
                    nearest = min(tiers, key=lambda t: abs(t - reduction_pct))
                    trade_value = current_position_value * (nearest / 100)
                    logger.info(f"REDUCE rounded {reduction_pct:.1f}% -> {nearest}% tier")
                else:
                    trade_value = reduction_amount

                projected_residual = max(current_position_value - trade_value, 0.0)
                if projected_residual < min_order:
                    logger.info(
                        f"REDUCE converted to SELL for {ticker}: residual £{projected_residual:.2f} "
                        f"below minimum £{min_order}"
                    )
                    execution_note = (
                        f"reduce_converted_to_sell_below_floor: residual £{projected_residual:.2f} < £{min_order:.2f}"
                    )
                    action = "SELL"
                    trade_value = current_position_value
                else:
                    if trade_value < min_order:
                        logger.info(
                            f"REDUCE skipped: reduction £{trade_value:.2f} below minimum £{min_order}"
                        )
                        self.notification_service.emit_trade_execution_result(
                            cycle_id=cycle_id,
                            payload={
                                "cycle_id": cycle_id,
                                "dry_run": self.dry_run,
                                "ticker": ticker,
                                "action": action,
                                "execution_status": "skipped",
                                "quantity": 0,
                                "price": current_price,
                                "value_gbp": trade_value,
                                "stop_loss_pct": decision.get("stop_loss_pct", 0),
                                "stop_loss_status": None,
                                "error_message": "below_min_order_value",
                                "reasoning_summary": decision.get("reasoning", ""),
                                "target_allocation_pct": final_alloc,
                                "occurred_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        return None

                    min_reduce_pct = self.settings.min_reduce_pct_of_position
                    if reduction_pct < min_reduce_pct:
                        logger.info(
                            f"REDUCE skipped: {reduction_pct:.1f}% below minimum {min_reduce_pct}%"
                        )
                        self.notification_service.emit_trade_execution_result(
                            cycle_id=cycle_id,
                            payload={
                                "cycle_id": cycle_id,
                                "dry_run": self.dry_run,
                                "ticker": ticker,
                                "action": action,
                                "execution_status": "skipped",
                                "quantity": 0,
                                "price": current_price,
                                "value_gbp": trade_value,
                                "stop_loss_pct": decision.get("stop_loss_pct", 0),
                                "stop_loss_status": None,
                                "error_message": "below_min_reduce_pct",
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
            price_gbp=price_gbp,
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
                        current_price_gbp=price_gbp,
                        stop_loss_pct=stop_loss_pct,
                        strategy=decision.get("primary_strategy"),
                    )
                    logger.info(
                        f"Stop-loss for {ticker}: {stop_loss_result.get('status')} "
                        f"@ {stop_loss_result.get('stop_price')}"
                    )
                except Exception as e:
                    logger.error(f"Failed to place stop-loss for {ticker}: {e}")
                    # P2-5: Alert when BUY fills but stop-loss fails
                    self.notification_service.emit_trade_without_stop(
                        cycle_id=cycle_id,
                        payload={
                            "cycle_id": cycle_id,
                            "dry_run": self.dry_run,
                            "ticker": ticker,
                            "action": action,
                            "quantity": exec_result.get("quantity", 0),
                            "price": current_price,
                            "stop_loss_pct": stop_loss_pct,
                            "error_message": str(e),
                            "occurred_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )

        # Also alert if BUY filled but no stop_loss_pct was provided
        if (
            action == "BUY"
            and exec_result.get("status") == "filled"
            and stop_loss_result is None
            and not self.dry_run
        ):
            if not stop_loss_pct or stop_loss_pct >= 0:
                logger.warning(f"BUY {ticker} filled without stop-loss (no stop_loss_pct in decision)")
                self.notification_service.emit_trade_without_stop(
                    cycle_id=cycle_id,
                    payload={
                        "cycle_id": cycle_id,
                        "dry_run": self.dry_run,
                        "ticker": ticker,
                        "action": action,
                        "quantity": exec_result.get("quantity", 0),
                        "price": current_price,
                        "stop_loss_pct": stop_loss_pct,
                        "error_message": "No stop_loss_pct in strategy decision",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

        notify_qty = exec_result.get("quantity")
        if notify_qty is None and current_price > 0:
            notify_qty = calculate_quantity(trade_value, current_price)

        self.notification_service.emit_trade_execution_result(
            cycle_id=cycle_id,
            payload={
                "cycle_id": cycle_id,
                "dry_run": self.dry_run,
                "ticker": ticker,
                "action": action,
                "target_allocation_pct": final_alloc,
                "execution_status": exec_result.get("status"),
                "quantity": notify_qty,
                "price": current_price,
                "value_gbp": exec_result.get("value_gbp", trade_value),
                "stop_loss_pct": stop_loss_pct,
                "stop_loss_status": (stop_loss_result or {}).get("status"),
                "stop_loss_error": (stop_loss_result or {}).get("error"),
                "error_message": exec_result.get("error"),
                "reasoning_summary": decision.get("reasoning", ""),
                "moderation_consensus": mod_result.consensus,
                "risk_verdict": risk_verdict.verdict,
                "execution_note": execution_note,
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
            "execution_note": execution_note,
        }

    def _get_top_tickers(self, sub_results: dict[str, Any]) -> list[str]:
        """Extract top tickers from sub-strategy results."""
        tickers: set[str] = set()
        for sig in sub_results.get("momentum", []):
            if sig.action == "BUY" and sig.score >= 75:
                tickers.add(sig.ticker)
        for sig in sub_results.get("mean_reversion", []):
            if sig.action == "BUY" and sig.score >= 70:
                tickers.add(sig.ticker)
        for score in sub_results.get("top_factor", []):
            tickers.add(score.ticker)
        return list(tickers)

    def _apply_risk_parity_sizing(
        self,
        *,
        decisions: list[dict[str, Any]],
        stocks_data: list[dict[str, Any]],
        portfolio_data: dict[str, Any],
        cash_pct: float,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Apply risk-parity sizing to BUY decisions before moderation/risk."""
        current_allocations = self._get_position_allocations(portfolio_data)
        close_prices_by_ticker = self._get_close_prices_by_ticker(stocks_data)
        sell_tickers = {
            str(decision.get("ticker", "")).strip().upper()
            for decision in decisions
            if decision.get("action") == "SELL"
        }
        buy_decisions = [decision for decision in decisions if decision.get("action") == "BUY"]
        sizings = self.risk_parity_sizer.size_buys(
            approved_buys=buy_decisions,
            current_allocations=current_allocations,
            close_prices_by_ticker=close_prices_by_ticker,
            sell_tickers=sell_tickers,
            cash_pct=cash_pct,
        )

        adjusted_decisions: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        for decision in decisions:
            if decision.get("action") != "BUY":
                adjusted_decisions.append(decision)
                continue

            ticker = str(decision.get("ticker", "")).strip().upper()
            sizing = sizings.get(ticker)
            if sizing is None:
                adjusted_decisions.append(decision)
                continue

            decision["risk_parity_target_allocation_pct"] = sizing.risk_parity_target_pct
            decision["risk_parity_trailing_vol_pct"] = sizing.trailing_vol_pct
            decision["risk_parity_applied"] = sizing.applied
            decision["risk_parity_sizing_reason"] = sizing.sizing_reason
            decision["target_allocation_pct"] = sizing.risk_parity_target_pct

            if not sizing.applied and sizing.sizing_reason == "already_at_or_above_target":
                rejections.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "stage": "risk_parity_filtered",
                    "reason": (
                        f"Risk parity target {sizing.risk_parity_target_pct:.2f}% is already met by "
                        f"current allocation"
                    ),
                    "conviction": decision.get("conviction", 0),
                    "moderation_consensus": "not invoked",
                    "decision": decision,
                    **self._get_stock_metadata(ticker, stocks_data),
                })
                continue

            adjusted_decisions.append(decision)

        return adjusted_decisions, rejections

    @staticmethod
    def _build_company_profiles(
        stocks_data: list[dict[str, Any]],
        top_tickers: list[str],
    ) -> str:
        """Build compact company profile text for Claude from fundamentals data.

        Extracts business_summary, industry, and sector for each top candidate
        so Claude can reason about qualitative factors like competitive moats,
        regulatory risk, and how macro news impacts the business.

        Fallback: when yfinance fundamentals lack industry/business_summary,
        uses Instrument table (enriched by bulk/backfill scripts).
        """
        profiles: list[str] = []
        data_by_ticker: dict[str, dict] = {}
        for stock in stocks_data:
            data_by_ticker[stock.get("ticker", "")] = stock

        # Fallback: load Instrument industry/summary for tickers missing from fundamentals
        t212_tickers = [t for t in (top_tickers[:self.settings.max_candidates] or []) if t]
        inst_by_ticker: dict[str, Instrument] = {}
        if t212_tickers:
            session = get_session()
            try:
                rows = session.query(Instrument).filter(
                    Instrument.ticker.in_(t212_tickers),
                    (Instrument.industry.isnot(None)) | (Instrument.business_summary.isnot(None)),
                ).all()
                inst_by_ticker = {r.ticker: r for r in rows}
            finally:
                session.close()

        for ticker in top_tickers[:self.settings.max_candidates]:
            stock = data_by_ticker.get(ticker, {})
            fundamentals = stock.get("fundamentals", {})
            summary = (fundamentals.get("business_summary") or "").strip()
            industry = (fundamentals.get("industry") or "").strip()
            sector = (fundamentals.get("sector") or "").strip()
            name = stock.get("name") or ticker

            # Fallback to Instrument when yfinance returns sparse data
            inst = inst_by_ticker.get(ticker)
            if inst:
                if not summary and inst.business_summary:
                    summary = (inst.business_summary or "").strip()
                if not industry and inst.industry:
                    industry = (inst.industry or "").strip()
                if not sector and inst.sector:
                    sector = (inst.sector or "").strip()
                if not name and inst.name:
                    name = inst.name or ticker

            if not summary:
                continue

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
        proactive_macro = macro.get("macro_state", {})
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
                "proactive_regime": proactive_macro.get("regime"),
                "proactive_confidence": proactive_macro.get("confidence_score"),
                "proactive_top_signals": proactive_macro.get("top_signals", []),
                "macro_action_plan": proactive_macro.get("action_plan", {}),
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

    @staticmethod
    def _is_losing_position(ticker: str, portfolio_data: dict) -> bool:
        """Check if a position is currently at a loss (audit fix H-1)."""
        for pos in portfolio_data.get("positions", []):
            pos_ticker = pos.get("ticker") or pos.get("instrument", {}).get("ticker", "")
            if pos_ticker == ticker:
                pnl = pos.get("pnl_pct") or pos.get("ppl", 0)
                return float(pnl) < 0
        return False

    def _get_current_price(self, ticker: str, stocks_data: list[dict]) -> float:
        for s in stocks_data:
            if s.get("ticker") == ticker:
                ind = s.get("indicators", {})
                return float(ind.get("current_price", 0))
        return 0.0

    def _compute_fx_price_gbp(
        self, current_price: float, ticker: str, portfolio_data: dict | None
    ) -> float:
        """Return current_price converted to GBP for quantity calculation.

        yfinance returns prices in the stock's native currency (USD for _US_EQ,
        GBX for _UK_EQ). Dividing a GBP allocation target by a USD price produces
        too few shares (~79% of intended for USD stocks). This method applies the
        account-level GBP/native-currency scale so quantity calculation is correct.

        The FX scale is derived from T212's own data:
            scale = invested_gbp / sum(qty × currentPrice_native)
        This is computed fresh each cycle and matches T212's live exchange rate.

        Falls back to current_price (scale=1.0) when the portfolio is empty (first
        trade ever) — safe degradation, same behaviour as before this feature.
        Only active when fx_aware_quantity=True in settings.
        """
        if not self.settings.fx_aware_quantity:
            return current_price
        if "_UK_EQ" in ticker:
            return current_price / 100  # GBX (pence) → GBP
        if "_US_EQ" not in ticker:
            return current_price  # Unknown suffix — no conversion
        positions = (portfolio_data or {}).get("positions", [])
        invested_gbp = float(
            (((portfolio_data or {}).get("account_summary") or {}).get("investments") or {})
            .get("currentValue", 0) or 0
        )
        scale = self._compute_position_value_scale(positions, invested_gbp)
        # scale == 1.0 when no positions exist (empty portfolio) — graceful fallback
        return current_price * scale

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
            yf_ticker = t212_to_yf(ticker)
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

    @staticmethod
    def _ticker_from_position(pos: dict) -> str:
        """Resolve ticker from T212 (instrument.ticker) or normalized format."""
        return (pos.get("instrument") or {}).get("ticker") or pos.get("ticker", "")

    @staticmethod
    def _compute_position_value_scale(positions: list[dict], invested_gbp: float) -> float:
        """Estimate FX/value scale when per-position walletImpact GBP fields are absent."""
        if invested_gbp <= 0:
            return 1.0
        native_total = 0.0
        for pos in positions:
            qty = float(pos.get("quantity", 0) or 0)
            price = float(pos.get("currentPrice", 0) or 0)
            if qty > 0 and price > 0:
                native_total += qty * price
        if native_total <= 0:
            return 1.0
        return invested_gbp / native_total

    @staticmethod
    def _normalize_position_for_snapshot(pos: dict, value_scale: float = 1.0) -> dict:
        """Convert T212 position format to dashboard schema (ticker, quantity, value_gbp, pnl_gbp, pnl_pct)."""
        ticker = Orchestrator._ticker_from_position(pos)
        quantity = float(pos.get("quantity", 0))
        current_price = float(pos.get("currentPrice", 0))
        wallet = pos.get("walletImpact") or {}
        raw_value_gbp = pos.get("value_gbp", 0) or 0
        if raw_value_gbp:
            value_gbp = float(raw_value_gbp)
        else:
            wallet_value = float(wallet.get("currentValue", 0) or 0)
            if wallet_value > 0:
                value_gbp = wallet_value
            else:
                native_value = quantity * current_price if quantity and current_price else 0.0
                value_gbp = native_value * value_scale

        raw_pnl_gbp = pos.get("pnl_gbp", 0) or 0
        if raw_pnl_gbp:
            pnl_gbp = float(raw_pnl_gbp)
        else:
            wallet_pnl = float(wallet.get("unrealizedProfitLoss", 0) or 0)
            if wallet_pnl != 0:
                pnl_gbp = wallet_pnl
            else:
                # T212 returns ppl + fxPpl when walletImpact is absent.
                pnl_gbp = float(pos.get("ppl", 0) or 0) + float(pos.get("fxPpl", 0) or 0)

        total_cost = float(wallet.get("totalCost", 0) or 0)
        if total_cost <= 0:
            avg_price = float(pos.get("averagePrice", 0) or 0)
            if avg_price > 0 and quantity > 0:
                total_cost = avg_price * quantity * value_scale
        pnl_pct = (pnl_gbp / total_cost * 100) if total_cost else 0.0
        return {"ticker": ticker, "quantity": quantity, "value_gbp": value_gbp, "pnl_gbp": pnl_gbp, "pnl_pct": pnl_pct}

    def _get_sector_allocations(self, portfolio_data: dict) -> dict[str, float]:
        """Compute sector allocation percentages from positions + Instrument metadata."""
        total = portfolio_data.get("total_value", 1)
        if total <= 0:
            return {}
        positions = portfolio_data.get("positions", [])
        if not positions:
            return {}

        sector_values: dict[str, float] = {}
        value_scale = self._compute_position_value_scale(
            positions,
            float(portfolio_data.get("invested", 0) or 0),
        )
        session = get_session()
        try:
            for pos in positions:
                ticker = self._ticker_from_position(pos)
                if not ticker:
                    continue
                norm = self._normalize_position_for_snapshot(pos, value_scale=value_scale)
                value = float(norm.get("value_gbp", 0) or 0)
                if value <= 0:
                    continue
                inst = session.query(Instrument).filter(Instrument.ticker == ticker).first()
                sector = inst.sector if inst and inst.sector else "Unknown"
                sector_values[sector] = sector_values.get(sector, 0) + value
        finally:
            session.close()

        return {sector: (val / total) * 100 for sector, val in sector_values.items()}

    def _get_position_allocations(self, portfolio_data: dict) -> dict[str, float]:
        total = portfolio_data.get("total_value", 1)
        if total <= 0:
            return {}
        result: dict[str, float] = {}
        positions = portfolio_data.get("positions", [])
        value_scale = self._compute_position_value_scale(
            positions,
            float(portfolio_data.get("invested", 0) or 0),
        )
        for pos in positions:
            ticker = self._ticker_from_position(pos)
            if not ticker:
                continue
            norm = self._normalize_position_for_snapshot(pos, value_scale=value_scale)
            value = float(norm.get("value_gbp", 0) or 0)
            result[ticker] = (value / total) * 100
        return result

    @staticmethod
    def _get_close_prices_by_ticker(stocks_data: list[dict[str, Any]]) -> dict[str, list[float]]:
        """Extract close-price history per ticker for risk-parity sizing."""
        result: dict[str, list[float]] = {}
        for stock in stocks_data:
            ticker = str(stock.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            closes = stock.get("indicators", {}).get("close_prices", [])
            if not closes:
                closes = stock.get("ohlcv", {}).get("close", [])
            if closes:
                result[ticker] = [float(value) for value in closes if value is not None]
        return result

    @staticmethod
    def _get_portfolio_returns(
        positions: list[dict], stocks_data: list[dict],
    ) -> dict[str, list[float]]:
        """Extract daily return series for held positions from stocks_data OHLCV.

        Used by RiskManager.check_correlation to detect dangerously correlated
        positions. (Audit fix H-3: was always passed as empty dict.)
        """
        data_by_ticker = {s.get("ticker", ""): s for s in stocks_data}
        returns: dict[str, list[float]] = {}
        for pos in positions:
            ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker", "")
            if not ticker:
                continue
            stock = data_by_ticker.get(ticker, {})
            # Try to get close prices from indicators/ohlcv
            closes = stock.get("indicators", {}).get("close_prices", [])
            if not closes:
                ohlcv = stock.get("ohlcv", {})
                closes = ohlcv.get("close", [])
            if len(closes) < 21:
                continue
            # Compute daily returns from close prices
            daily_returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    daily_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
            if len(daily_returns) >= 20:
                returns[ticker] = daily_returns
        return returns

    @staticmethod
    def _build_position_pnl_summary(portfolio_data: dict) -> str:
        """Build a tabular position P&L summary for the strategy prompt."""
        positions = portfolio_data.get("positions", [])
        if not positions:
            return ""
        lines = ["Ticker | Value (GBP) | P&L (GBP) | P&L (%) | Qty"]
        lines.append("--- | --- | --- | --- | ---")
        value_scale = Orchestrator._compute_position_value_scale(
            positions,
            float(portfolio_data.get("invested", 0) or 0),
        )
        for pos in positions:
            ticker = Orchestrator._ticker_from_position(pos)
            if not ticker:
                continue
            norm = Orchestrator._normalize_position_for_snapshot(pos, value_scale=value_scale)
            lines.append(
                f"{ticker} | {norm['value_gbp']:.0f} | {norm['pnl_gbp']:.2f} | {norm['pnl_pct']:.1f}% | {norm['quantity']:.2f}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_strategy_performance_summary() -> str:
        """Query PerformanceMetric for latest win rates by strategy."""
        session = get_session()
        try:
            metrics = (
                session.query(PerformanceMetric)
                .filter(PerformanceMetric.metric_name.in_([
                    "win_rate_momentum", "win_rate_mean_reversion", "win_rate_factor",
                    "total_trades", "sharpe_ratio_30d", "sortino_ratio_30d",
                    "max_drawdown_pct",
                ]))
                .order_by(PerformanceMetric.calculated_at.desc())
                .limit(20)
                .all()
            )
            if not metrics:
                return ""
            latest: dict[str, float] = {}
            for m in metrics:
                if m.metric_name not in latest and m.metric_value is not None:
                    latest[m.metric_name] = m.metric_value
            if not latest:
                return ""
            lines = []
            if "win_rate_momentum" in latest:
                lines.append(f"- Momentum win rate: {latest['win_rate_momentum']:.0f}%")
            if "win_rate_mean_reversion" in latest:
                lines.append(f"- Mean Reversion win rate: {latest['win_rate_mean_reversion']:.0f}%")
            if "win_rate_factor" in latest:
                lines.append(f"- Factor win rate: {latest['win_rate_factor']:.0f}%")
            if "total_trades" in latest:
                lines.append(f"- Total completed trades: {latest['total_trades']:.0f}")
            if "sharpe_ratio_30d" in latest:
                lines.append(f"- Sharpe ratio (30d): {latest['sharpe_ratio_30d']:.2f}")
            if "sortino_ratio_30d" in latest:
                lines.append(f"- Sortino ratio (30d): {latest['sortino_ratio_30d']:.2f}")
            if "max_drawdown_pct" in latest:
                lines.append(f"- Max drawdown: {latest['max_drawdown_pct']:.1f}%")
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""
        finally:
            session.close()

    def _save_snapshot(self, portfolio_data: dict, state: str) -> None:
        """Save a portfolio snapshot. Positions are normalised from T212 format for dashboard display."""
        session = get_session()
        try:
            raw_positions = portfolio_data.get("positions", [])
            value_scale = self._compute_position_value_scale(
                raw_positions,
                float(portfolio_data.get("invested", 0) or 0),
            )
            normalised = [self._normalize_position_for_snapshot(p, value_scale=value_scale) for p in raw_positions]

            benchmark_value, benchmark_pnl_pct, alpha_pct = None, None, None
            try:
                benchmark_value, benchmark_pnl_pct, alpha_pct = self._compute_benchmark_alpha(
                    session, portfolio_data.get("total_return_pct", 0)
                )
            except Exception as e:
                logger.debug(f"Benchmark alpha computation skipped: {e}")

            session.add(PortfolioSnapshot(
                timestamp=datetime.now(timezone.utc),
                total_value_gbp=portfolio_data.get("total_value", 0),
                cash_gbp=portfolio_data.get("cash", 0),
                invested_gbp=portfolio_data.get("invested", 0),
                pnl_gbp=0.0,
                pnl_pct=portfolio_data.get("total_return_pct", 0),
                benchmark_value=benchmark_value,
                benchmark_pnl_pct=benchmark_pnl_pct,
                alpha_pct=alpha_pct,
                num_positions=portfolio_data.get("num_positions", 0),
                positions_json=json.dumps(normalised, default=str),
                state=state,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def _compute_benchmark_alpha(
        session: Any, portfolio_return_pct: float
    ) -> tuple[float | None, float | None, float | None]:
        """Compute SPY benchmark return since first snapshot for alpha calculation."""
        first_snap = (
            session.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.asc())
            .first()
        )
        if not first_snap:
            return None, None, None

        inception_date = first_snap.timestamp
        try:
            import yfinance as yf

            spy = yf.Ticker("SPY")
            hist = spy.history(start=inception_date.strftime("%Y-%m-%d"), period="1d")
            if hist.empty or len(hist) < 2:
                return None, None, None

            spy_start = float(hist["Close"].iloc[0])
            spy_now = float(hist["Close"].iloc[-1])
            benchmark_pnl_pct = ((spy_now - spy_start) / spy_start) * 100
            alpha_pct = portfolio_return_pct - benchmark_pnl_pct
            return spy_now, benchmark_pnl_pct, alpha_pct
        except Exception:
            return None, None, None

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
        def _pos_ticker(p: dict) -> str:
            return (p.get("instrument") or {}).get("ticker") or p.get("ticker", "")

        def _pos_value(p: dict) -> float:
            v = p.get("value_gbp") or p.get("value")
            if v is not None:
                return float(v)
            w = p.get("walletImpact") or {}
            return float(w.get("currentValue", 0))

        summary["active_positions"] = [
            {"ticker": _pos_ticker(p), "quantity": p.get("quantity"), "value_gbp": _pos_value(p)}
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
@click.option("--reset-peak", "do_reset_peak", is_flag=True, help="Reset peak to current portfolio value and clear CAUTIOUS")
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
    do_reset_peak: bool,
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

        if do_reset_peak:
            try:
                portfolio_data = orchestrator._get_portfolio_state()
                current = float(portfolio_data.get("total_value", 0))
                if current <= 0:
                    click.echo("Cannot reset peak: portfolio value is 0 or missing", err=True)
                else:
                    orchestrator.state_machine.reset_peak_to_current(current)
                    click.echo(f"Peak reset to {current:.2f}, state -> ACTIVE")
            except Exception as e:
                click.echo(f"Reset peak failed: {e}", err=True)
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
