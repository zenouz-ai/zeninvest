"""Single-ticker pipeline for Slack trade commands (US-1.6).

Runs the full pipeline (data → strategy → moderation → risk → execution) for one
ticker with user-intent override. Reuses all existing agent components.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.agents.execution.order_manager import OrderManager
from src.agents.execution.t212_client import T212Client
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.moderation.panel import ModerationPanel
from src.agents.notifications.trade_command_parser import TradeCommandIntent
from src.agents.risk.risk_manager import RiskManager
from src.agents.strategy.engine import StrategyEngine
from src.data.database import get_session
from src.data.models import Instrument, SlackCommandLog, StrategyDecision
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("single_ticker_run")


@dataclass
class PreparedTradeExecution:
    """Prepared execution payload used for confirmation + final order placement."""

    action: str
    target_amount_gbp: float
    current_price: float
    quantity_override: float | None
    strategy: str = "slack_command"
    conviction: int = 0
    moderation_result: str = ""
    risk_result: str = ""


@dataclass
class SingleTickerResult:
    """Result of a single-ticker pipeline run."""

    ticker_t212: str
    ticker_yf: str
    cycle_id: str
    user_action: str  # BUY, SELL, REVIEW

    # Pipeline outputs
    strategy_decision: dict[str, Any] | None = None
    moderation_result: dict[str, Any] | None = None
    risk_verdict: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None

    # Status
    status: str = "pending"  # executed, rejected, review_only, error
    rejection_reason: str | None = None
    error_message: str | None = None

    # Convenience fields for formatting
    conviction: int = 0
    strategy_action: str = ""
    moderation_consensus: str = ""
    risk_verdict_str: str = ""
    price: float = 0.0
    quantity: float = 0.0
    value_gbp: float = 0.0
    command_log_id: int | None = None
    prepared_execution: PreparedTradeExecution | None = field(default=None, repr=False)


class SingleTickerRunner:
    """Run the full investment pipeline for a single ticker with user-intent override."""

    def __init__(self, dry_run: bool = False) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run
        self.data_fetcher = DataFetcher()
        self.strategy_engine = StrategyEngine()
        self.moderation_panel = ModerationPanel()
        self.risk_manager = RiskManager()
        self._t212_client: T212Client | None = None
        self._order_manager: OrderManager | None = None

    @property
    def t212_client(self) -> T212Client:
        if self._t212_client is None:
            self._t212_client = T212Client()
        return self._t212_client

    @property
    def order_manager(self) -> OrderManager:
        if self._order_manager is None:
            self._order_manager = OrderManager(dry_run=self.dry_run)
        return self._order_manager

    def run(
        self,
        ticker_t212: str,
        intent: TradeCommandIntent,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
    ) -> SingleTickerResult:
        """Execute single-ticker pipeline with user intent override."""
        result = self.prepare(
            ticker_t212=ticker_t212,
            intent=intent,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        if result.status != "ready":
            return result
        return self.execute_prepared(result)

    def prepare(
        self,
        ticker_t212: str,
        intent: TradeCommandIntent,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
    ) -> SingleTickerResult:
        """Prepare a single-ticker run through risk without placing an order."""
        ticker_yf = t212_to_yf(ticker_t212)
        cycle_id = f"slack-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

        result = SingleTickerResult(
            ticker_t212=ticker_t212,
            ticker_yf=ticker_yf,
            cycle_id=cycle_id,
            user_action=intent.action,
        )

        # Log command receipt
        cmd_log = self._log_command(
            intent=intent,
            ticker_t212=ticker_t212,
            cycle_id=cycle_id,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        result.command_log_id = cmd_log

        try:
            # --- Pre-flight validation ---
            validation_error = self._validate_preflight(ticker_t212, intent)
            if validation_error:
                result.status = "rejected"
                result.rejection_reason = validation_error
                self._update_command_log(cmd_log, "rejected", rejection_reason=validation_error)
                return result

            # --- Phase 1: Data ---
            logger.info(f"[{cycle_id}] Fetching data for {ticker_yf}")
            stock_data = self.data_fetcher.get_stock_analysis_lite(ticker_yf)
            if not stock_data or stock_data.get("error"):
                result.status = "error"
                result.error_message = f"Data fetch failed for {ticker_yf}"
                self._update_command_log(cmd_log, "error", rejection_reason=result.error_message)
                return result

            current_price = self._extract_price(stock_data)
            if not current_price or current_price <= 0:
                result.status = "error"
                result.error_message = f"Could not determine price for {ticker_yf}"
                self._update_command_log(cmd_log, "error", rejection_reason=result.error_message)
                return result
            result.price = current_price

            # --- Phase 2: Sub-strategy scoring ---
            stocks_data_list = [stock_data]
            existing_positions = self._get_existing_positions()
            sub_results = self.strategy_engine.run_sub_strategies(
                stocks_data_list, existing_positions
            )

            # --- Phase 3: Strategy synthesis ---
            logger.info(f"[{cycle_id}] Running strategy synthesis for {ticker_t212}")
            portfolio_data = self._get_portfolio_data()
            portfolio_state_str = json.dumps(portfolio_data, indent=2, default=str)[:2000]

            strategy_result = self.strategy_engine.synthesize_with_claude(
                sub_strategy_results=sub_results,
                portfolio_state=portfolio_state_str,
                market_regime="unknown",
                analyst_data="",
                news_sentiment="",
                macro_context="",
                company_profiles=self._get_company_profile(ticker_t212),
                system_state="ACTIVE",
                vix=None,
                cash_pct=portfolio_data.get("cash_pct", 10.0),
                num_positions=len(existing_positions),
                cycle_id=cycle_id,
            )

            # Extract strategy decision for this ticker
            decisions = strategy_result.get("decisions", [])
            strategy_decision = None
            for d in decisions:
                if d.get("ticker", "").upper() in (ticker_t212.upper(), ticker_yf.upper()):
                    strategy_decision = d
                    break
            if not strategy_decision and decisions:
                strategy_decision = decisions[0]

            if strategy_decision:
                result.strategy_decision = strategy_decision
                result.conviction = strategy_decision.get("conviction", 0)
                result.strategy_action = strategy_decision.get("action", "HOLD")

                # Persist strategy decision
                self._persist_strategy_decision(strategy_decision, cycle_id)

            final_action = intent.action
            try:
                target_allocation_pct, target_amount_gbp, quantity_override = self._resolve_user_sizing(
                    ticker_t212=ticker_t212,
                    intent=intent,
                    strategy_decision=strategy_decision,
                    total_value=portfolio_data.get("total_value", 10000),
                    current_price=current_price,
                )
            except ValueError as e:
                result.status = "rejected"
                result.rejection_reason = str(e)
                self._update_command_log(cmd_log, "rejected", rejection_reason=result.rejection_reason)
                return result
            result.quantity = abs(quantity_override) if quantity_override is not None else (
                abs(target_amount_gbp / current_price) if current_price > 0 else 0.0
            )
            result.value_gbp = max(target_amount_gbp, 0.0)

            # --- Phase 4: Moderation ---
            logger.info(f"[{cycle_id}] Running moderation for {ticker_t212}")
            if strategy_decision:
                moderation_action = strategy_decision.get("action", "HOLD") if intent.action == "REVIEW" else final_action
                moderation_alloc = (
                    strategy_decision.get("target_allocation_pct", 5.0)
                    if intent.action == "REVIEW"
                    else target_allocation_pct
                )
                trade_proposal = {
                    "ticker": ticker_t212,
                    "action": moderation_action,
                    "target_allocation_pct": moderation_alloc,
                    "conviction": result.conviction,
                    "reasoning": strategy_decision.get("reasoning", ""),
                    "stop_loss_pct": strategy_decision.get("stop_loss_pct", -8),
                }
                market_context = {
                    "indicators": stock_data.get("indicators", {}),
                    "fundamentals": stock_data.get("fundamentals", {}),
                }
                mod_result = self.moderation_panel.review_trade(
                    trade_proposal=trade_proposal,
                    portfolio_context=portfolio_state_str,
                    market_context=market_context,
                    conviction=result.conviction,
                    cycle_id=cycle_id,
                )
                result.moderation_result = mod_result.to_dict()
                result.moderation_consensus = mod_result.consensus

                if intent.action != "REVIEW" and result.moderation_consensus == "BLOCKED":
                    result.status = "rejected"
                    result.rejection_reason = "BLOCKED by moderation consensus"
                    self._update_command_log(
                        cmd_log,
                        "rejected",
                        rejection_reason=result.rejection_reason,
                    )
                    logger.info(f"[{cycle_id}] {ticker_t212} BLOCKED by moderation panel")
                    return result

            # --- Phase 5: REVIEW stops here ---
            if intent.action == "REVIEW":
                result.status = "review_only"
                self._update_command_log(cmd_log, "review_only")
                logger.info(
                    f"[{cycle_id}] REVIEW complete for {ticker_t212}: "
                    f"{result.strategy_action} (conviction {result.conviction}), "
                    f"moderation={result.moderation_consensus}"
                )
                return result

            # --- Phase 6: Risk evaluation ---
            logger.info(f"[{cycle_id}] Running risk check for {final_action} {ticker_t212}")
            sector = self._get_sector(ticker_t212)
            current_portfolio = self._get_current_portfolio_pcts()
            sector_allocations = self._get_sector_allocations()

            risk_verdict = self.risk_manager.evaluate_trade(
                ticker=ticker_t212,
                action=final_action,
                proposed_allocation_pct=target_allocation_pct,
                sector=sector,
                current_portfolio=current_portfolio,
                sector_allocations=sector_allocations,
                portfolio_returns={},
                current_value=portfolio_data.get("total_value", 10000),
                peak_value=portfolio_data.get("total_value", 10000),
                cash_pct=portfolio_data.get("cash_pct", 10.0),
                vix=None,
                daily_pnl_pct=0.0,
                daily_loss_halt_until=None,
                num_positions=len(existing_positions),
                system_state="ACTIVE",
                cycle_id=cycle_id,
                conviction=result.conviction,
            )

            result.risk_verdict = {
                "verdict": risk_verdict.verdict,
                "triggered_rules": risk_verdict.triggered_rules,
                "reasoning": risk_verdict.reasoning,
            }
            result.risk_verdict_str = risk_verdict.verdict

            if risk_verdict.verdict == "REJECT":
                if intent.force:
                    # User explicitly overrode risk VETO via a force prefix.
                    logger.warning(
                        f"[{cycle_id}] {intent.action} {ticker_t212} RISK VETO OVERRIDDEN by user "
                        f"(force=True): {risk_verdict.reasoning}"
                    )
                    result.risk_verdict_str = "OVERRIDDEN"
                else:
                    result.status = "rejected"
                    result.rejection_reason = f"Risk VETO: {risk_verdict.reasoning}"
                    self._update_command_log(cmd_log, "rejected", rejection_reason=result.rejection_reason)
                    logger.info(f"[{cycle_id}] {intent.action} {ticker_t212} REJECTED by risk: {risk_verdict.reasoning}")
                    return result

            # Apply risk resize if needed
            if (
                final_action == "BUY"
                and risk_verdict.verdict == "RESIZE"
                and risk_verdict.adjusted_allocation_pct is not None
            ):
                target_allocation_pct = risk_verdict.adjusted_allocation_pct
                resized_amount_gbp = portfolio_data.get("total_value", 10000) * (target_allocation_pct / 100.0)
                target_amount_gbp = min(target_amount_gbp, resized_amount_gbp)
                if quantity_override is not None and current_price > 0:
                    quantity_override = min(quantity_override, target_amount_gbp / current_price)
                result.quantity = abs(quantity_override) if quantity_override is not None else (
                    abs(target_amount_gbp / current_price) if current_price > 0 else 0.0
                )
                result.value_gbp = max(target_amount_gbp, 0.0)

            result.prepared_execution = PreparedTradeExecution(
                action=final_action,
                target_amount_gbp=target_amount_gbp,
                current_price=current_price,
                quantity_override=quantity_override,
                conviction=result.conviction,
                moderation_result=result.moderation_consensus,
                risk_result=result.risk_verdict_str,
            )
            result.status = "ready"
            return result

        except Exception as e:
            logger.error(f"[{cycle_id}] Single-ticker pipeline error: {e}", exc_info=True)
            result.status = "error"
            result.error_message = str(e)
            self._update_command_log(cmd_log, "error", rejection_reason=str(e))
            return result

    def execute_prepared(self, result: SingleTickerResult) -> SingleTickerResult:
        """Execute a previously prepared trade."""
        if result.prepared_execution is None:
            raise ValueError("SingleTickerResult has no prepared execution payload")

        execution = result.prepared_execution
        logger.info(f"[{result.cycle_id}] Executing {execution.action} {result.ticker_t212}")

        exec_result = self.order_manager.execute_market_order(
            ticker=result.ticker_t212,
            action=execution.action,
            target_amount_gbp=execution.target_amount_gbp,
            current_price=execution.current_price,
            strategy=execution.strategy,
            conviction=execution.conviction,
            moderation_result=execution.moderation_result,
            risk_result=execution.risk_result,
            quantity_override=execution.quantity_override,
        )

        result.execution_result = exec_result
        result.quantity = abs(exec_result.get("quantity", 0))
        result.value_gbp = exec_result.get("value_gbp", 0)

        if exec_result.get("status") in ("filled", "dry_run", "pending"):
            result.status = "executed"
            self._update_command_log(
                result.command_log_id,
                "executed",
                order_id=exec_result.get("order_id"),
            )
            logger.info(
                f"[{result.cycle_id}] {result.user_action} {result.ticker_t212} EXECUTED: "
                f"qty={result.quantity:.2f}, value=£{result.value_gbp:.2f}, "
                f"status={exec_result.get('status')}"
            )
        elif exec_result.get("status") == "skipped":
            result.status = "rejected"
            result.rejection_reason = self._format_execution_rejection(exec_result)
            self._update_command_log(
                result.command_log_id,
                "rejected",
                rejection_reason=result.rejection_reason,
            )
            logger.info(
                f"[{result.cycle_id}] {result.user_action} {result.ticker_t212} SKIPPED: "
                f"{result.rejection_reason}"
            )
        else:
            result.status = "error"
            result.error_message = exec_result.get("reason", "Execution failed")
            self._update_command_log(
                result.command_log_id,
                "error",
                rejection_reason=result.error_message,
            )
            logger.warning(
                f"[{result.cycle_id}] {result.user_action} {result.ticker_t212} FAILED: "
                f"{result.error_message}"
            )

        return result

    def _format_execution_rejection(self, exec_result: dict[str, Any]) -> str:
        """Translate execution skip reasons into user-friendly rejection messages."""
        reason = str(exec_result.get("reason", "")).strip()
        if reason == "below_min_order_value":
            value = float(exec_result.get("value_gbp", 0) or 0)
            min_order = float(self.settings.min_order_value_gbp)
            return (
                f"Order value £{value:.2f} is below the minimum order size "
                f"of £{min_order:.2f}"
            )
        if reason == "duplicate":
            return "A matching order was already placed recently."
        if reason == "zero_quantity":
            return "Calculated order quantity is zero."
        return reason or "Execution failed"

    def _validate_preflight(self, ticker_t212: str, intent: TradeCommandIntent) -> str | None:
        """Run pre-flight validation. Returns error message or None if ok."""
        if intent.action == "BUY":
            try:
                cash = self._get_available_cash_gbp()
                if intent.amount_gbp and cash < intent.amount_gbp:
                    return f"Insufficient cash. Available: £{cash:.2f}, requested: £{intent.amount_gbp:.2f}"
            except Exception as e:
                logger.warning(f"Cash validation skipped: {e}")

        elif intent.action == "SELL":
            try:
                position = self.t212_client.get_position(ticker_t212)
                qty = float(position.get("quantity", 0))
                if qty <= 0:
                    return f"No open position in {ticker_t212}"
                if intent.quantity_shares and intent.quantity_shares > qty:
                    return f"Requested {intent.quantity_shares} shares but only hold {qty}"
            except Exception as e:
                logger.warning(f"Position validation skipped: {e}")

        return None

    def _extract_price(self, stock_data: dict[str, Any]) -> float | None:
        """Extract current price from stock data."""
        indicators = stock_data.get("indicators", {})
        if indicators and isinstance(indicators, dict):
            price = indicators.get("current_price") or indicators.get("close")
            if price is not None:
                return float(price)
        fundamentals = stock_data.get("fundamentals", {})
        if fundamentals and isinstance(fundamentals, dict):
            price = fundamentals.get("currentPrice") or fundamentals.get("previousClose")
            if price is not None:
                return float(price)
        return None

    def _resolve_user_sizing(
        self,
        ticker_t212: str,
        intent: TradeCommandIntent,
        strategy_decision: dict[str, Any] | None,
        total_value: float,
        current_price: float,
    ) -> tuple[float, float, float | None]:
        """Resolve the user-intended allocation and value before risk/execution."""
        if intent.action == "SELL":
            position = self.t212_client.get_position(ticker_t212)
            pos_qty = float(position.get("quantity", 0))
            if pos_qty <= 0:
                raise ValueError(f"No position in {ticker_t212}")

            quantity_override = intent.quantity_shares or pos_qty
            target_amount_gbp = quantity_override * current_price
            return 0.0, target_amount_gbp, quantity_override

        base_allocation_pct = strategy_decision.get("target_allocation_pct", 5.0) if strategy_decision else 5.0
        quantity_override = intent.quantity_shares

        if intent.amount_gbp is not None:
            target_amount_gbp = float(intent.amount_gbp)
        elif quantity_override is not None:
            target_amount_gbp = float(quantity_override) * current_price
        else:
            target_amount_gbp = total_value * (base_allocation_pct / 100.0)

        target_allocation_pct = (target_amount_gbp / total_value * 100) if total_value > 0 else 0.0
        return target_allocation_pct, target_amount_gbp, quantity_override

    def _get_existing_positions(self) -> set[str]:
        """Get set of currently held ticker IDs."""
        try:
            positions = self.t212_client.get_portfolio()
            return {p.get("ticker", "") for p in positions if p.get("quantity", 0) > 0}
        except Exception:
            return set()

    def _get_portfolio_data(self) -> dict[str, Any]:
        """Get portfolio summary for strategy context."""
        try:
            try:
                account_summary = self.t212_client.get_account_summary()
            except Exception as e:
                logger.warning(f"Account summary unavailable for single-ticker run, using fallback data: {e}")
                account_summary = {}

            try:
                cash_data = self.t212_client.get_cash()
            except Exception as e:
                logger.warning(f"Cash endpoint unavailable for single-ticker run, falling back to summary cash: {e}")
                cash_data = account_summary.get("cash", {})

            try:
                positions = self.t212_client.get_portfolio()
            except Exception:
                positions = []

            total = self._get_total_value_gbp(account_summary, cash_data, positions)
            cash = self._extract_available_cash(cash_data if cash_data else account_summary.get("cash", {}))
            cash_pct = (cash / total * 100) if total > 0 else 10.0
            return {"total_value": total, "cash": cash, "cash_pct": cash_pct}
        except Exception:
            return {"total_value": 10000, "cash": 1000, "cash_pct": 10.0}

    def _get_company_profile(self, ticker_t212: str) -> str:
        """Get company profile from Instrument table."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
            if inst:
                parts = []
                if inst.name:
                    parts.append(f"{inst.name}")
                if inst.sector:
                    parts.append(f"Sector: {inst.sector}")
                if inst.industry:
                    parts.append(f"Industry: {inst.industry}")
                if inst.business_summary:
                    parts.append(inst.business_summary[:500])
                return " | ".join(parts) if parts else ""
            return ""
        except Exception:
            return ""
        finally:
            session.close()

    def _get_sector(self, ticker_t212: str) -> str:
        """Get sector for a ticker from Instrument table."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
            return inst.sector or "Unknown" if inst else "Unknown"
        except Exception:
            return "Unknown"
        finally:
            session.close()

    def _get_current_portfolio_pcts(self) -> dict[str, float]:
        """Get current portfolio allocation percentages."""
        try:
            positions = self.t212_client.get_portfolio()
            try:
                account_summary = self.t212_client.get_account_summary()
            except Exception:
                account_summary = {}
            try:
                cash_data = self.t212_client.get_cash()
            except Exception:
                cash_data = account_summary.get("cash", {})
            total = self._get_total_value_gbp(account_summary, cash_data, positions)
            return {
                p.get("ticker", ""): float(p.get("currentValue", 0)) / total * 100
                for p in positions
                if p.get("quantity", 0) > 0
            }
        except Exception:
            return {}

    def _extract_available_cash(self, cash_data: Any) -> float:
        """Extract the free/available-to-trade cash from a T212 cash payload."""
        if isinstance(cash_data, dict):
            return float(cash_data.get("free") or cash_data.get("availableToTrade") or 0)
        return float(cash_data or 0)

    def _extract_reserved_cash(self, cash_data: Any) -> float:
        """Extract reserved cash from a T212 cash payload."""
        if isinstance(cash_data, dict):
            return float(
                cash_data.get("reservedForOrders")
                or cash_data.get("blocked")
                or cash_data.get("reserved")
                or 0
            )
        return 0.0

    def _get_total_value_gbp(
        self,
        account_summary: dict[str, Any],
        cash_data: Any,
        positions: list[dict[str, Any]],
    ) -> float:
        """Compute total value, preferring account summary and falling back to cash + positions."""
        total_value_raw = account_summary.get("totalValue")
        if total_value_raw is not None:
            return float(total_value_raw)

        cash = self._extract_available_cash(cash_data)
        reserved = self._extract_reserved_cash(cash_data)
        invested = float((account_summary.get("investments") or {}).get("currentValue", 0) or 0)
        if invested <= 0:
            invested = sum(float(p.get("currentValue", 0) or 0) for p in positions)
        total = cash + invested + reserved
        return total if total > 0 else 10000.0

    def _get_available_cash_gbp(self) -> float:
        """Return the free/available-to-trade cash balance."""
        try:
            cash_data = self.t212_client.get_cash()
            cash = self._extract_available_cash(cash_data)
            if cash > 0:
                return cash
        except Exception as e:
            logger.warning(f"Cash endpoint unavailable during preflight validation: {e}")

        account_summary = self.t212_client.get_account_summary()
        return self._extract_available_cash(account_summary.get("cash", {}))

    def _get_sector_allocations(self) -> dict[str, float]:
        """Get sector allocation percentages."""
        try:
            portfolio = self._get_current_portfolio_pcts()
            session = get_session()
            try:
                sectors: dict[str, float] = {}
                for ticker, pct in portfolio.items():
                    inst = session.query(Instrument).filter(Instrument.ticker == ticker).first()
                    sector = inst.sector if inst and inst.sector else "Unknown"
                    sectors[sector] = sectors.get(sector, 0) + pct
                return sectors
            finally:
                session.close()
        except Exception:
            return {}

    def _persist_strategy_decision(self, decision: dict[str, Any], cycle_id: str) -> None:
        """Persist strategy decision to DB."""
        session = get_session()
        try:
            sd = StrategyDecision(
                cycle_id=cycle_id,
                ticker=decision.get("ticker", ""),
                action=decision.get("action", "HOLD"),
                conviction=decision.get("conviction", 0),
                target_allocation_pct=decision.get("target_allocation_pct", 0),
                reasoning=decision.get("reasoning", "")[:2000],
                stop_loss_pct=decision.get("stop_loss_pct"),
            )
            session.add(sd)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to persist strategy decision: {e}")
        finally:
            session.close()

    def _log_command(
        self,
        intent: TradeCommandIntent,
        ticker_t212: str,
        cycle_id: str,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
    ) -> int | None:
        """Log Slack command to slack_command_log table. Returns log ID."""
        session = get_session()
        try:
            log = SlackCommandLog(
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=thread_ts,
                raw_message=intent.raw_message,
                parsed_intent_json=intent.to_json(),
                ticker=ticker_t212,
                action=intent.action,
                cycle_id=cycle_id,
                status="processing",
            )
            session.add(log)
            session.commit()
            return log.id
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to log slack command: {e}")
            return None
        finally:
            session.close()

    def _update_command_log(
        self,
        log_id: int | None,
        status: str | None = None,
        order_id: int | None = None,
        rejection_reason: str | None = None,
        response_message: str | None = None,
    ) -> None:
        """Update existing command log entry."""
        if log_id is None:
            return
        session = get_session()
        try:
            log = session.query(SlackCommandLog).filter(SlackCommandLog.id == log_id).first()
            if log:
                if status is not None:
                    log.status = status
                if order_id is not None:
                    log.order_id = order_id
                if rejection_reason:
                    log.rejection_reason = rejection_reason
                if response_message is not None:
                    log.response_message = response_message
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to update command log: {e}")
        finally:
            session.close()

    def update_command_log_entry(
        self,
        log_id: int | None,
        status: str | None = None,
        order_id: int | None = None,
        rejection_reason: str | None = None,
        response_message: str | None = None,
    ) -> None:
        """Public wrapper for updating Slack command log fields."""
        self._update_command_log(
            log_id=log_id,
            status=status,
            order_id=order_id,
            rejection_reason=rejection_reason,
            response_message=response_message,
        )

    def close(self) -> None:
        """Clean up resources."""
        self.data_fetcher.close()
        if self._t212_client:
            self._t212_client.close()
