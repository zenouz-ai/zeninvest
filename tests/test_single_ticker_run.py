"""Tests for single-ticker pipeline (US-1.6)."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.notifications.trade_command_parser import TradeCommandIntent
from src.data.models import Base, SlackCommandLog, StrategyDecision
from src.orchestrator.single_ticker_run import SingleTickerResult, SingleTickerRunner


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_runner(db_session):
    """Create a SingleTickerRunner with all external deps mocked."""
    with patch("src.orchestrator.single_ticker_run.get_session", return_value=db_session), \
         patch("src.orchestrator.single_ticker_run.DataFetcher") as mock_df, \
         patch("src.orchestrator.single_ticker_run.StrategyEngine") as mock_se, \
         patch("src.orchestrator.single_ticker_run.ModerationPanel") as mock_mp, \
         patch("src.orchestrator.single_ticker_run.RiskManager") as mock_rm:

        # Configure DataFetcher mock
        df_instance = mock_df.return_value
        df_instance.get_stock_analysis_lite.return_value = {
            "ticker": "AAPL",
            "indicators": {"close": 150.0, "rsi": 55},
            "fundamentals": {"currentPrice": 150.0, "sector": "Technology"},
        }
        df_instance.close.return_value = None

        # Configure StrategyEngine mock
        se_instance = mock_se.return_value
        se_instance.run_sub_strategies.return_value = {"signals": []}
        se_instance.synthesize_with_claude.return_value = {
            "decisions": [{
                "ticker": "AAPL_US_EQ",
                "action": "HOLD",
                "conviction": 65,
                "target_allocation_pct": 5.0,
                "reasoning": "Stock is fairly valued",
                "stop_loss_pct": -8,
            }]
        }

        # Configure ModerationPanel mock
        mp_instance = mock_mp.return_value
        mod_result = MagicMock()
        mod_result.consensus = "APPROVED"
        mod_result.to_dict.return_value = {"consensus": "APPROVED"}
        mp_instance.review_trade.return_value = mod_result

        # Configure RiskManager mock
        rm_instance = mock_rm.return_value
        risk_verdict = MagicMock()
        risk_verdict.verdict = "APPROVE"
        risk_verdict.triggered_rules = []
        risk_verdict.reasoning = "All checks passed"
        risk_verdict.adjusted_allocation_pct = None
        rm_instance.evaluate_trade.return_value = risk_verdict

        runner = SingleTickerRunner(dry_run=True)

        # Mock T212Client
        mock_t212 = MagicMock()
        mock_t212.get_account_summary.return_value = {
            "totalValue": 10000, "cash": {"free": 5000}
        }
        mock_t212.get_positions.return_value = []
        mock_t212.get_position.return_value = {"quantity": 10}
        runner._t212_client = mock_t212

        # Mock OrderManager
        mock_om = MagicMock()
        mock_om.execute_market_order.return_value = {
            "status": "dry_run",
            "ticker": "AAPL_US_EQ",
            "quantity": 3.0,
            "price": 150.0,
            "value_gbp": 450.0,
            "order_id": 1,
        }
        runner._order_manager = mock_om

        yield runner, {
            "data_fetcher": df_instance,
            "strategy_engine": se_instance,
            "moderation_panel": mp_instance,
            "risk_manager": rm_instance,
            "t212_client": mock_t212,
            "order_manager": mock_om,
        }


class TestSingleTickerRunner:

    def test_buy_pipeline_executes(self, mock_runner):
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"
        assert result.user_action == "BUY"
        assert result.ticker_t212 == "AAPL_US_EQ"
        assert result.cycle_id.startswith("slack-")
        mocks["order_manager"].execute_market_order.assert_called_once()

    def test_review_no_execution(self, mock_runner):
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="REVIEW", ticker="AAPL", raw_message="REVIEW AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "review_only"
        assert result.strategy_decision is not None
        assert result.moderation_consensus == "APPROVED"
        mocks["order_manager"].execute_market_order.assert_not_called()

    def test_sell_pipeline(self, mock_runner):
        runner, mocks = mock_runner
        mocks["t212_client"].get_position.return_value = {"quantity": 10}
        intent = TradeCommandIntent(
            action="SELL", ticker="AAPL", raw_message="SELL AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"
        assert result.user_action == "SELL"

    def test_risk_veto_rejects(self, mock_runner):
        runner, mocks = mock_runner
        risk_verdict = MagicMock()
        risk_verdict.verdict = "REJECT"
        risk_verdict.triggered_rules = ["max_single_stock"]
        risk_verdict.reasoning = "Single stock cap exceeded"
        risk_verdict.adjusted_allocation_pct = None
        mocks["risk_manager"].evaluate_trade.return_value = risk_verdict

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "rejected"
        assert "Risk VETO" in result.rejection_reason
        mocks["order_manager"].execute_market_order.assert_not_called()

    def test_sell_no_position_rejected(self, mock_runner):
        runner, mocks = mock_runner
        mocks["t212_client"].get_position.return_value = {"quantity": 0}
        intent = TradeCommandIntent(
            action="SELL", ticker="AAPL", raw_message="SELL AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "rejected"
        assert "No open position" in (result.rejection_reason or "")

    def test_data_fetch_failure(self, mock_runner):
        runner, mocks = mock_runner
        mocks["data_fetcher"].get_stock_analysis_lite.return_value = {"error": "timeout"}

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "error"

    def test_user_override_logs_strategy_opinion(self, mock_runner):
        """User says BUY but strategy says HOLD — both recorded."""
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.strategy_action == "HOLD"
        assert result.user_action == "BUY"
        assert result.status == "executed"

    def test_buy_with_quantity(self, mock_runner):
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", quantity_shares=5, raw_message="BUY 5 AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"
        call_kwargs = mocks["order_manager"].execute_market_order.call_args
        assert call_kwargs.kwargs.get("quantity_override") == 5 or \
               (call_kwargs[1].get("quantity_override") == 5 if len(call_kwargs) > 1 else True)

    def test_buy_with_amount_gbp(self, mock_runner):
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", amount_gbp=500, raw_message="BUY £500 AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"


class TestSingleTickerResult:

    def test_default_values(self):
        result = SingleTickerResult(
            ticker_t212="AAPL_US_EQ",
            ticker_yf="AAPL",
            cycle_id="slack-20260323T120000",
            user_action="BUY",
        )
        assert result.status == "pending"
        assert result.rejection_reason is None
        assert result.conviction == 0
