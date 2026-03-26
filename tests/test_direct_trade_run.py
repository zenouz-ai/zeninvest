"""Tests for direct Slack trade execution and cancel runner flows."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.notifications.cancel_command_runner import CancelCommandRunner
from src.agents.notifications.trade_command_parser import TradeCommandIntent
from src.data.models import Base, SlackCommandLog
from src.orchestrator.direct_trade_run import DirectTradeRunner


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
def direct_runner(db_session):
    with patch("src.orchestrator.direct_trade_run.log_slack_command", return_value=1), \
         patch("src.orchestrator.direct_trade_run.update_slack_command_log"), \
         patch("src.orchestrator.direct_trade_run.DataFetcher") as mock_df:
        df_instance = mock_df.return_value
        df_instance.get_stock_analysis_lite.return_value = {
            "indicators": {"current_price": 150.0},
            "fundamentals": {"currentPrice": 150.0},
        }
        df_instance.close.return_value = None

        runner = DirectTradeRunner(dry_run=True)
        mock_t212 = MagicMock()
        mock_t212.get_account_summary.return_value = {"totalValue": 10000, "cash": {"free": 5000}}
        mock_t212.get_cash.return_value = {"free": 5000}
        mock_t212.get_portfolio.return_value = []
        mock_t212.get_position.return_value = {"quantity": 8}
        runner._t212_client = mock_t212

        mock_om = MagicMock()
        mock_om.execute_market_order.return_value = {
            "status": "dry_run",
            "ticker": "AAPL_US_EQ",
            "quantity": 3.33,
            "price": 150.0,
            "value_gbp": 500.0,
            "order_id": 42,
        }
        runner._order_manager = mock_om
        yield runner, {"t212_client": mock_t212, "order_manager": mock_om}


class TestDirectTradeRunner:
    def test_plain_buy_defaults_to_direct_mode_and_executes(self, direct_runner):
        runner, mocks = direct_runner
        intent = TradeCommandIntent(
            action="BUY",
            ticker="AAPL",
            raw_message="BUY AAPL",
            command_kind="trade",
            execution_mode="direct",
            subject_phrases=["AAPL"],
        )

        result = runner.run("AAPL_US_EQ", intent)

        assert result.status == "executed"
        assert result.execution_mode == "direct"
        assert result.strategy_decision is None
        call = mocks["order_manager"].execute_market_order.call_args.kwargs
        assert call["strategy"] == "slack_direct"
        assert call["target_amount_gbp"] == pytest.approx(500.0)

    def test_direct_sell_uses_full_position_when_no_quantity_given(self, direct_runner):
        runner, mocks = direct_runner
        intent = TradeCommandIntent(
            action="SELL",
            ticker="AAPL",
            raw_message="SELL AAPL",
            command_kind="trade",
            execution_mode="direct",
            subject_phrases=["AAPL"],
        )

        prepared = runner.prepare("AAPL_US_EQ", intent)

        assert prepared.status == "ready"
        assert prepared.quantity == pytest.approx(8.0)
        call = prepared.prepared_execution
        assert call is not None
        assert call.strategy == "slack_direct"


class TestCancelCommandRunner:
    @patch("src.agents.notifications.cancel_command_runner.log_slack_command", return_value=1)
    @patch("src.agents.notifications.cancel_command_runner.update_slack_command_log")
    def test_partial_cancel_result_sets_partial_status(self, mock_update, _mock_log):
        runner = CancelCommandRunner(dry_run=False)
        mock_om = MagicMock()
        mock_om.cancel_pending_orders_by_class.return_value = {
            "status": "partial",
            "cancelled": ["1"],
            "matches": [{"order_id": "1"}],
            "failures": [{"ticker": "MSFT_US_EQ", "order_id": "2", "error": "500"}],
        }
        runner._order_manager = mock_om

        intent = TradeCommandIntent(
            action="CANCEL",
            ticker="NVDA",
            raw_message="cancel stop sell NVDA, Microsoft",
            command_kind="cancel",
            execution_mode="cancel_only",
            cancel_order_class="stop_sell",
            subject_phrases=["NVDA", "Microsoft"],
        )

        result = runner.run(ticker_t212s=["NVDA_US_EQ", "MSFT_US_EQ"], intent=intent)

        assert result.status == "partial"
        assert result.cancel_order_class == "stop_sell"
        assert result.target_tickers == ["NVDA_US_EQ", "MSFT_US_EQ"]
        assert result.result_details is not None
        mock_update.assert_called()
