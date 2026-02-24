"""Orchestrator — main control loop for the investment agent.

Runs every 12 hours during market hours (configurable).
Sequence: Data -> Strategy -> Moderation -> Risk -> Execution -> Journal
"""

import json
import sys
import uuid
from datetime import datetime
from typing import Any

import click

from src.agents.execution.order_manager import OrderManager
from src.agents.execution.t212_client import T212Client
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.moderation.panel import ModerationPanel
from src.agents.reporting.journal import generate_trade_journal
from src.agents.risk.risk_manager import RiskManager
from src.agents.strategy.engine import StrategyEngine
from src.data.database import get_session
from src.data.models import Base, PortfolioSnapshot
from src.orchestrator.state_machine import StateMachine
from src.utils.config import get_settings
from src.utils.cost_tracker import DegradationLevel, get_cost_summary, get_degradation_level
from src.utils.logger import get_logger

logger = get_logger("orchestrator")


class Orchestrator:
    """Main orchestrator that wires all agents together."""

    def __init__(self, dry_run: bool = False) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run
        self.state_machine = StateMachine()
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
            self._order_manager = OrderManager(client=self.t212_client, dry_run=self.dry_run)
        return self._order_manager

    def run_cycle(self) -> dict[str, Any]:
        """Run a full investment cycle.

        Sequence: Data -> Strategy -> Moderation -> Risk -> Execution -> Journal
        """
        cycle_id = f"cycle_{datetime.utcnow().strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:6]}"
        logger.info(f"Starting cycle {cycle_id} (dry_run={self.dry_run})")

        result: dict[str, Any] = {"cycle_id": cycle_id, "trades": [], "errors": []}

        # Check if system is paused
        if self.state_machine.is_paused:
            logger.info("System is PAUSED. Skipping cycle.")
            result["status"] = "paused"
            return result

        # Check cost degradation
        degradation = get_degradation_level()
        if degradation == DegradationLevel.HALTED:
            logger.error("All LLM budgets exceeded. Skipping cycle.")
            result["status"] = "budget_halted"
            return result
        if degradation == DegradationLevel.NO_STRATEGY:
            logger.warning("Anthropic budget exceeded. Skipping strategy cycle.")
            result["status"] = "budget_no_strategy"
            return result

        current_state = self.state_machine.current_state

        # --- STEP 1: HALTED state handling ---
        if current_state == "HALTED":
            logger.error("System is HALTED. Liquidating all positions.")
            if not self.dry_run:
                liquidation = self.order_manager.liquidate_all()
                result["liquidation"] = liquidation
            result["status"] = "halted_liquidation"
            return result

        # --- STEP 2: Get portfolio state ---
        try:
            portfolio_data = self._get_portfolio_state()
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            result["errors"].append(f"portfolio_state: {e}")
            result["status"] = "error"
            return result

        current_value = portfolio_data["total_value"]
        cash_gbp = portfolio_data["cash"]
        cash_pct = (cash_gbp / current_value * 100) if current_value > 0 else 100

        # Update peak and check drawdown
        self.state_machine.update_peak(current_value)
        state_info = self.state_machine.get_state()
        peak_value = state_info.get("peak_portfolio_value", current_value)

        drawdown_state = self.risk_manager.get_drawdown_state(current_value, peak_value)
        if drawdown_state != current_state:
            self.state_machine.transition(drawdown_state, f"Drawdown check at {current_value:.2f}")
            current_state = drawdown_state

        if current_state == "HALTED":
            logger.error("Drawdown triggered HALT. Liquidating.")
            if not self.dry_run:
                self.order_manager.liquidate_all()
            result["status"] = "halted_drawdown"
            return result

        drawdown_pct = ((peak_value - current_value) / peak_value * 100) if peak_value > 0 else 0
        self.state_machine.update_drawdown(drawdown_pct)

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

        # Get data for universe (use cached instruments or a small set for now)
        stocks_data = self._fetch_stocks_data(portfolio_data.get("positions", []))

        # Get Alpha Vantage broad sentiment
        av_sentiment = {}
        try:
            av_sentiment = self.data_fetcher.alpha_vantage.get_broad_market_sentiment()
        except Exception as e:
            logger.warning(f"Alpha Vantage unavailable: {e}")

        # --- STEP 4: Run strategies ---
        logger.info("Running strategies...")
        existing_tickers = {p.get("ticker", "") for p in portfolio_data.get("positions", [])}

        sub_results = self.strategy_engine.run_sub_strategies(stocks_data, existing_tickers)

        # Gather Finnhub sentiment for top candidates
        finnhub_data_map: dict[str, dict] = {}
        top_tickers = self._get_top_tickers(sub_results)
        for ticker in top_tickers[:15]:
            try:
                yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
                finnhub_data_map[ticker] = self.data_fetcher.finnhub.get_full_sentiment_data(yf_ticker)
            except Exception as e:
                logger.warning(f"Finnhub error for {ticker}: {e}")
                finnhub_data_map[ticker] = {}

        finnhub_summary = json.dumps(finnhub_data_map, indent=2, default=str)[:3000]
        av_summary = json.dumps(av_sentiment, indent=2, default=str)[:2000]

        # Claude synthesis
        portfolio_state_str = json.dumps(portfolio_data, indent=2, default=str)[:2000]
        strategy_result = self.strategy_engine.synthesize_with_claude(
            sub_strategy_results=sub_results,
            portfolio_state=portfolio_state_str,
            market_regime=market_regime,
            finnhub_sentiment=finnhub_summary,
            alpha_vantage_sentiment=av_summary,
            system_state=current_state,
            vix=vix,
            cash_pct=cash_pct,
            num_positions=len(existing_tickers),
            cycle_id=cycle_id,
        )

        if "error" in strategy_result and not strategy_result.get("decisions"):
            logger.error(f"Strategy synthesis failed: {strategy_result['error']}")
            result["errors"].append(f"strategy: {strategy_result['error']}")
            result["status"] = "strategy_error"
            self.state_machine.record_cycle()
            return result

        decisions = strategy_result.get("decisions", [])
        logger.info(f"Strategy produced {len(decisions)} decisions")

        # --- STEP 5: Moderation -> Risk -> Execution ---
        for decision in decisions:
            ticker = decision.get("ticker", "")
            action = decision.get("action", "HOLD")
            conviction = decision.get("conviction", 0)
            target_alloc = decision.get("target_allocation_pct", 0)

            if action == "HOLD":
                continue

            # Moderation
            logger.info(f"Moderating {action} {ticker}...")
            mod_result = self.moderation_panel.review_trade(
                trade_proposal=decision,
                portfolio_context=portfolio_state_str,
                sentiment_data=json.dumps(finnhub_data_map.get(ticker, {}), default=str),
                conviction=conviction,
                cycle_id=cycle_id,
            )

            if mod_result.consensus == "BLOCKED":
                logger.info(f"{ticker} BLOCKED by moderation panel")
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
                num_positions=len(existing_tickers),
                system_state=current_state,
                is_existing_winner=ticker in existing_tickers,
                cycle_id=cycle_id,
            )

            if risk_verdict.verdict == "REJECT":
                logger.info(f"{ticker} REJECTED by risk: {risk_verdict.reasoning}")
                continue

            final_alloc = risk_verdict.adjusted_allocation_pct or target_alloc
            trade_value = current_value * final_alloc / 100
            current_price = self._get_current_price(ticker, stocks_data)

            if current_price <= 0:
                logger.warning(f"No price for {ticker}, skipping")
                continue

            # Execute
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

            # Journal
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
                    finnhub_data=finnhub_data_map.get(ticker, {}),
                    alpha_vantage_data=av_sentiment,
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
                        "total_return_pct": portfolio_data.get("total_return_pct", 0),
                        "alpha_pct": portfolio_data.get("alpha_pct", 0),
                        "positions": [],
                    },
                )
                exec_result["journal_path"] = journal_path
            except Exception as e:
                logger.error(f"Journal generation failed for {ticker}: {e}")

            result["trades"].append({
                "ticker": ticker,
                "action": action,
                "allocation_pct": final_alloc,
                "execution": exec_result,
                "moderation": mod_result.consensus,
                "risk": risk_verdict.verdict,
            })

        # Record cycle completion
        self.state_machine.record_cycle()
        self._save_snapshot(portfolio_data, current_state)

        result["status"] = "completed"
        result["num_trades"] = len(result["trades"])
        result["cost_summary"] = get_cost_summary(days=1)
        logger.info(f"Cycle {cycle_id} completed: {len(result['trades'])} trades executed")
        return result

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

        # cash_data may be a dict from T212 API or a plain float (mock)
        if isinstance(cash_data, dict):
            cash = float(cash_data.get("free", 0))
        else:
            cash = float(cash_data)

        invested = sum(
            float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
            for p in positions
        )
        total_value = cash + invested

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

    def _fetch_stocks_data(self, current_positions: list[dict]) -> list[dict[str, Any]]:
        """Fetch analysis data for stocks in universe and current positions."""
        stocks_data: list[dict[str, Any]] = []

        # Analyze current positions
        for pos in current_positions:
            ticker = pos.get("ticker", "")
            if not ticker:
                continue
            yf_ticker = ticker.replace("_US_EQ", "").replace("_UK_EQ", "")
            try:
                cached = self.data_fetcher.get_cached_data(yf_ticker, "full_analysis")
                if cached:
                    stocks_data.append(cached)
                else:
                    data = self.data_fetcher.get_stock_analysis(yf_ticker)
                    data["ticker"] = ticker
                    stocks_data.append(data)
            except Exception as e:
                logger.warning(f"Failed to fetch data for {ticker}: {e}")
                stocks_data.append({"ticker": ticker, "indicators": {}, "fundamentals": {}})

        return stocks_data

    def _get_top_tickers(self, sub_results: dict[str, Any]) -> list[str]:
        """Extract top tickers from sub-strategy results."""
        tickers: set[str] = set()
        for signal in sub_results.get("momentum", []):
            if signal.action == "BUY" and signal.score >= 60:
                tickers.add(signal.ticker)
        for signal in sub_results.get("mean_reversion", []):
            if signal.action == "BUY" and signal.score >= 55:
                tickers.add(signal.ticker)
        for score in sub_results.get("top_factor", []):
            tickers.add(score.ticker)
        return list(tickers)

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
                timestamp=datetime.utcnow(),
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

@click.command()
@click.option("--dry-run", is_flag=True, help="Run without executing trades")
@click.option("--force-sell", "force_sell_ticker", default=None, help="Force sell a position")
@click.option("--pause", is_flag=True, help="Pause the system")
@click.option("--resume", "do_resume", is_flag=True, help="Resume the system")
@click.option("--report", is_flag=True, help="Generate a status report")
@click.option("--status", is_flag=True, help="Show system status")
def main(
    dry_run: bool,
    force_sell_ticker: str | None,
    pause: bool,
    do_resume: bool,
    report: bool,
    status: bool,
) -> None:
    """Investment Agent Orchestrator."""
    orchestrator = Orchestrator(dry_run=dry_run)

    try:
        if status:
            s = orchestrator.get_status()
            click.echo(json.dumps(s, indent=2, default=str))
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
        click.echo(json.dumps(result, indent=2, default=str))

    finally:
        orchestrator.close()


if __name__ == "__main__":
    main()
