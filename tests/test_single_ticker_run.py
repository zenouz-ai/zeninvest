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
        mock_t212.get_cash.return_value = {"free": 5000}
        mock_t212.get_portfolio.return_value = []
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

    def test_moderation_reviews_user_intent_not_strategy_action(self, mock_runner):
        """Moderation should review the final user action, even when strategy disagrees."""
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL"
        )

        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"
        trade_proposal = mocks["moderation_panel"].review_trade.call_args.kwargs["trade_proposal"]
        assert trade_proposal["action"] == "BUY"

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

    def test_buy_with_available_to_trade_cash_field(self, mock_runner):
        runner, mocks = mock_runner
        mocks["t212_client"].get_cash.return_value = {"availableToTrade": 8665.04}
        mocks["t212_client"].get_account_summary.return_value = {
            "cash": {"availableToTrade": 8665.04},
            "investments": {"currentValue": 1334.96},
        }

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", amount_gbp=500, raw_message="BUY £500 AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"

    def test_buy_uses_account_summary_cash_when_cash_endpoint_unavailable(self, mock_runner):
        runner, mocks = mock_runner
        mocks["t212_client"].get_cash.side_effect = RuntimeError("429")
        mocks["t212_client"].get_account_summary.return_value = {
            "cash": {"availableToTrade": 8665.04},
            "investments": {"currentValue": 1334.96},
        }

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", amount_gbp=500, raw_message="BUY £500 AAPL"
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"

    def test_force_buy_bypasses_risk_veto(self, mock_runner):
        """Force buy should override risk REJECT and proceed to execution."""
        runner, mocks = mock_runner
        risk_verdict = MagicMock()
        risk_verdict.verdict = "REJECT"
        risk_verdict.triggered_rules = ["cash_floor"]
        risk_verdict.reasoning = "Cash floor breached"
        risk_verdict.adjusted_allocation_pct = None
        mocks["risk_manager"].evaluate_trade.return_value = risk_verdict

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="force buy AAPL", force=True
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "executed"
        assert result.risk_verdict_str == "OVERRIDDEN"
        mocks["order_manager"].execute_market_order.assert_called_once()

    def test_non_force_buy_rejected_by_risk(self, mock_runner):
        """Normal buy (force=False) should still be rejected by risk VETO."""
        runner, mocks = mock_runner
        risk_verdict = MagicMock()
        risk_verdict.verdict = "REJECT"
        risk_verdict.triggered_rules = ["cash_floor"]
        risk_verdict.reasoning = "Cash floor breached"
        risk_verdict.adjusted_allocation_pct = None
        mocks["risk_manager"].evaluate_trade.return_value = risk_verdict

        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", raw_message="BUY AAPL", force=False
        )
        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "rejected"
        assert "Risk VETO" in result.rejection_reason
        mocks["order_manager"].execute_market_order.assert_not_called()

    def test_review_logs_review_only_status(self, mock_runner, db_session):
        runner, mocks = mock_runner
        intent = TradeCommandIntent(
            action="REVIEW", ticker="AAPL", raw_message="REVIEW AAPL"
        )

        result = runner.run(ticker_t212="AAPL_US_EQ", intent=intent)

        assert result.status == "review_only"
        log = db_session.query(SlackCommandLog).order_by(SlackCommandLog.id.desc()).first()
        assert log is not None
        assert log.status == "review_only"


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


class TestExtractPrice:
    """Tests for SingleTickerRunner._extract_price()."""

    @pytest.fixture
    def runner(self, db_session):
        """Create a SingleTickerRunner with deps mocked."""
        with patch("src.orchestrator.single_ticker_run.get_session", return_value=db_session), \
             patch("src.orchestrator.single_ticker_run.DataFetcher"), \
             patch("src.orchestrator.single_ticker_run.StrategyEngine"), \
             patch("src.orchestrator.single_ticker_run.ModerationPanel"), \
             patch("src.orchestrator.single_ticker_run.RiskManager"):
            r = SingleTickerRunner(dry_run=True)
            yield r

    def test_extract_from_indicators_current_price(self, runner):
        stock_data = {"indicators": {"current_price": 150.25, "close": 149.0}}
        assert runner._extract_price(stock_data) == 150.25

    def test_fallback_to_indicators_close(self, runner):
        stock_data = {"indicators": {"close": 149.0}}
        assert runner._extract_price(stock_data) == 149.0

    def test_fallback_to_fundamentals_current_price(self, runner):
        stock_data = {"indicators": {}, "fundamentals": {"currentPrice": 151.50}}
        assert runner._extract_price(stock_data) == 151.50

    def test_fallback_to_fundamentals_previous_close(self, runner):
        stock_data = {"indicators": {}, "fundamentals": {"previousClose": 148.75}}
        assert runner._extract_price(stock_data) == 148.75

    def test_returns_none_when_no_price_available(self, runner):
        stock_data = {"indicators": {}, "fundamentals": {}}
        assert runner._extract_price(stock_data) is None

    def test_returns_none_for_empty_data(self, runner):
        assert runner._extract_price({}) is None

    def test_handles_indicators_error_dict_gracefully(self, runner):
        """When indicators contains an 'error' key (a dict), don't crash."""
        stock_data = {"indicators": {"error": "timeout"}, "fundamentals": {"currentPrice": 100.0}}
        # indicators has no price keys, should fall through to fundamentals
        assert runner._extract_price(stock_data) == 100.0

    def test_handles_indicators_error_string_gracefully(self, runner):
        """When indicators is a non-dict (e.g. error string), fall through."""
        stock_data = {"indicators": "error", "fundamentals": {"currentPrice": 100.0}}
        assert runner._extract_price(stock_data) == 100.0
