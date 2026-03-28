"""Tests for the execution agent — T212 client and order manager."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

import httpx
from tenacity import RetryError, Future

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, Instrument, Order

try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None
from src.agents.execution.t212_client import (
    T212Client,
    _is_retryable,
    _t212_time_validity,
    calculate_quantity,
)
from src.agents.execution.order_manager import OrderManager


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _event_logger_session_factory(db_session):
    """Return a sessionmaker for the event_logger worker.
    The event_logger runs in a background thread and must not share the main test
    session (SQLAlchemy sessions are not thread-safe). Each call gets a new
    session from the same engine.
    """
    return sessionmaker(bind=db_session.get_bind())


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    """Patch get_session to use the test database."""
    event_logger_SessionLocal = (
        _event_logger_session_factory(db_session)
        if DashboardBase is not None
        else lambda: db_session
    )
    with patch("src.agents.execution.order_manager.get_session", return_value=db_session), patch(
        "dashboard.backend.app.services.event_logger.SessionLocal",
        event_logger_SessionLocal,
    ):
        yield


class TestT212Client:
    def test_get_position_returns_empty_dict_on_404(self):
        """404 'no position' is expected when ticker not held — should return {} not raise."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"detail":"No open position found for AAPL_US_EQ"}'
        mock_response.headers = {}

        mock_settings = MagicMock()
        mock_settings.t212_base_url = "https://demo.trading212.com"
        mock_settings.t212_api_key = "test_key"
        mock_settings.t212_api_secret = "test_secret"

        with patch("src.agents.execution.t212_client.get_session"), \
             patch("src.agents.execution.t212_client.get_settings", return_value=mock_settings), \
             patch("httpx.Client") as mock_client_class, \
             patch.object(T212Client, "_check_rate_limit"):
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response
            client = T212Client()
            result = client.get_position("AAPL_US_EQ")

        assert result == {}
        assert result.get("quantity", 0) == 0


class TestCalculateQuantity:
    def test_basic_calculation(self):
        # £500 at £100/share = 5.00 shares
        assert calculate_quantity(500.0, 100.0) == 5.00

    def test_floors_to_two_decimals(self):
        # £1000 at £33.33 = 30.003 -> floors to 30.00
        qty = calculate_quantity(1000.0, 33.33)
        assert qty == 30.00

    def test_fractional_shares(self):
        # £100 at £150.00 = 0.666... -> floors to 0.66
        qty = calculate_quantity(100.0, 150.0)
        assert qty == 0.66

    def test_zero_price(self):
        assert calculate_quantity(500.0, 0.0) == 0.0

    def test_negative_price(self):
        assert calculate_quantity(500.0, -10.0) == 0.0

    def test_small_amount(self):
        # £10 at £200 = 0.05
        assert calculate_quantity(10.0, 200.0) == 0.05


class TestOrderManager:
    def test_dry_run_buy(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=525.0,
            current_price=175.0,
            strategy="momentum",
            conviction=80,
        )

        assert result["status"] == "dry_run"
        assert result["ticker"] == "AAPL_US_EQ"
        assert result["action"] == "BUY"
        assert result["quantity"] > 0
        mock_client.place_market_order.assert_not_called()

        # Check order was logged
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].status == "dry_run"

    def test_dry_run_sell(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="TSLA_US_EQ",
            action="SELL",
            target_amount_gbp=300.0,
            current_price=250.0,
        )

        assert result["status"] == "dry_run"
        assert result["action"] == "SELL"
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].status == "dry_run"

    def test_buy_below_min_order_value_upgrades_to_floor(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=100.0,
            current_price=100.0,
        )

        assert result["status"] == "dry_run"
        assert result["value_gbp"] == 500.0
        assert db_session.query(Order).count() == 1
        assert db_session.query(Order).first().value_gbp == 500.0

    def test_buy_at_floor_allows_quantity_rounding_dip(self, db_session):
        """Target>=min should allow BUY even if quantity flooring makes computed value dip slightly below."""
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        # Raw shares = 500/333.33 = 1.500015... => floors to 1.50
        # Computed order value = 1.50 * 333.33 = 499.995 < 500.
        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=333.33,
            strategy="momentum",
            conviction=80,
        )

        assert result["status"] == "dry_run"
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].status == "dry_run"
        # With target-based enforcement, logged value_gbp should match the target.
        assert orders[0].value_gbp == 500.0

    def test_reduce_below_buy_floor_still_executes_and_logs(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="REDUCE",
            target_amount_gbp=100.0,
            current_price=100.0,
        )

        assert result["status"] == "dry_run"
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].action == "REDUCE"
        assert orders[0].status == "dry_run"

    def test_duplicate_detection(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        # First order
        result1 = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=525.0,
            current_price=175.0,
        )
        assert result1["status"] == "dry_run"

        # Same order again (should be duplicate)
        result2 = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=525.0,
            current_price=175.0,
        )
        assert result2["status"] == "skipped"
        assert result2["reason"] == "duplicate"

    def test_dry_run_market_order_adds_off_hours_warning_note(self, db_session, monkeypatch):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)
        monkeypatch.setattr(
            "src.agents.execution.order_manager.is_within_regular_market_session",
            lambda settings: False,
        )

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=525.0,
            current_price=175.0,
            strategy="momentum",
            conviction=80,
        )

        order = db_session.query(Order).one()
        assert result["status"] == "dry_run"
        assert result["warning_note"] is not None
        assert order.warning_note == result["warning_note"]

    def test_in_hours_market_order_has_no_warning_note(self, db_session, monkeypatch):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)
        monkeypatch.setattr(
            "src.agents.execution.order_manager.is_within_regular_market_session",
            lambda settings: True,
        )

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=525.0,
            current_price=175.0,
            strategy="momentum",
            conviction=80,
        )

        order = db_session.query(Order).one()
        assert result["status"] == "dry_run"
        assert result.get("warning_note") is None
        assert order.warning_note is None

    def test_stop_loss_adds_off_hours_warning_note(self, db_session, monkeypatch):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)
        monkeypatch.setattr(
            "src.agents.execution.order_manager.is_within_regular_market_session",
            lambda settings: False,
        )

        result = manager.place_stop_loss(
            ticker="AAPL_US_EQ",
            quantity=2.0,
            current_price=100.0,
            stop_loss_pct=-10.0,
        )

        order = db_session.query(Order).one()
        assert result["status"] == "dry_run"
        assert result["warning_note"] is not None
        assert order.warning_note == result["warning_note"]

    def test_zero_quantity_skipped(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="BRK.A_US_EQ",
            action="BUY",
            target_amount_gbp=1.0,
            current_price=500000.0,  # Too expensive
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "zero_quantity"

    def test_live_order_success(self, db_session):
        mock_client = MagicMock()
        mock_client.place_market_order.return_value = {"id": "t212-order-123", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.execute_market_order(
            ticker="MSFT_US_EQ",
            action="BUY",
            target_amount_gbp=1000.0,
            current_price=400.0,
        )

        assert result["status"] == "filled"
        assert result["t212_order_id"] == "t212-order-123"
        mock_client.place_market_order.assert_called_once()

    def test_live_order_failure(self, db_session):
        mock_client = MagicMock()
        mock_client.place_market_order.side_effect = Exception("API error")

        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.execute_market_order(
            ticker="GOOG_US_EQ",
            action="BUY",
            target_amount_gbp=600.0,
            current_price=150.0,
        )

        assert result["status"] == "failed"
        assert "API error" in result["error"]
        assert result["quantity"] == 4.0
        assert result["price"] == 150.0
        assert result["value_gbp"] == 600.0
        assert "order_id" in result

        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].status == "failed"

    def test_live_order_http_failure_includes_response_body(self, db_session):
        mock_client = MagicMock()
        response = MagicMock()
        response.status_code = 400
        response.text = '{"detail":"Minimum order value not met"}'
        mock_client.place_market_order.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=response,
        )

        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.execute_market_order(
            ticker="GOOG_US_EQ",
            action="BUY",
            target_amount_gbp=600.0,
            current_price=150.0,
        )

        assert result["status"] == "failed"
        assert "HTTP 400" in result["error"]
        assert "Minimum order value not met" in result["error"]

    def test_buy_marks_instrument_unavailable_on_not_tradable_http_400(self, db_session):
        db_session.add(Instrument(ticker="BIO_B_US_EQ", data_available=True))
        db_session.commit()

        mock_client = MagicMock()
        response = MagicMock()
        response.status_code = 400
        response.text = (
            '{"type":"/api-errors/instrument-invisible","title":"Error while placing the order",'
            '"status":400,"detail":"Instrument can not be traded."}'
        )
        mock_client.place_market_order.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=response,
        )

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="BIO_B_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=25.0,
        )

        assert result["status"] == "failed"
        db_session.expire_all()
        inst = db_session.query(Instrument).filter(Instrument.ticker == "BIO_B_US_EQ").one()
        assert inst.data_available is False

    def test_portfolio_state(self):
        mock_client = MagicMock()
        mock_client.get_cash.return_value = {"free": 5000.0, "total": 10000.0}
        mock_client.get_portfolio.return_value = [
            {"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 175.0},
        ]
        mock_client.get_account_summary.return_value = {}  # Fallback to cash+portfolio

        manager = OrderManager(client=mock_client)
        state = manager.get_portfolio_state()

        assert state["cash"]["free"] == 5000.0
        assert state["num_positions"] == 1

    def test_liquidate_all(self, db_session):
        mock_client = MagicMock()
        mock_client.get_portfolio.return_value = [
            {"ticker": "AAPL_US_EQ", "quantity": 10},
            {"ticker": "MSFT_US_EQ", "quantity": 5},
        ]
        # T212 returns FILLED status — liquidate_all now maps it properly (C-3 fix)
        mock_client.place_market_order.return_value = {"id": "liquidation-123", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        results = manager.liquidate_all()

        assert len(results) == 2
        assert all(r["status"] == "filled" for r in results)
        assert mock_client.place_market_order.call_count == 2

    def test_liquidate_all_pending_status(self, db_session):
        """When T212 returns no status, liquidate_all should map to 'pending' not 'filled'."""
        mock_client = MagicMock()
        mock_client.get_portfolio.return_value = [
            {"ticker": "AAPL_US_EQ", "quantity": 10},
        ]
        mock_client.place_market_order.return_value = {"id": "liquidation-456"}

        manager = OrderManager(client=mock_client, dry_run=False)
        results = manager.liquidate_all()

        assert len(results) == 1
        assert results[0]["status"] == "pending"

    def test_place_stop_loss_success(self, db_session):
        mock_client = MagicMock()
        mock_client.place_stop_order.return_value = {"id": 12345}
        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.place_stop_loss(
            ticker="VRTX_US_EQ",
            quantity=1.59,
            current_price=501.47,
            stop_loss_pct=-8.0,
        )

        assert result["status"] == "placed"
        assert result["stop_price"] == 461.35  # 501.47 * 0.92
        mock_client.place_stop_order.assert_called_once()
        call_kwargs = mock_client.place_stop_order.call_args[1]
        assert call_kwargs["time_validity"] == "GTC"

    def test_place_stop_loss_sends_good_till_cancel_to_t212(self, db_session):
        """T212 API expects GOOD_TILL_CANCEL, not GTC; t212_client maps GTC -> GOOD_TILL_CANCEL."""
        mock_client = MagicMock()
        mock_client.place_stop_order.return_value = {"id": 999}
        manager = OrderManager(client=mock_client, dry_run=False)

        manager.place_stop_loss(
            ticker="AAPL_US_EQ",
            quantity=5.0,
            current_price=175.0,
            stop_loss_pct=-8.0,
        )

        mock_client.place_stop_order.assert_called_once_with(
            ticker="AAPL_US_EQ",
            quantity=-5.0,
            stop_price=161.0,
            time_validity="GTC",
        )
        assert _t212_time_validity("GTC") == "GOOD_TILL_CANCEL"
        assert _t212_time_validity("DAY") == "DAY"

    def test_place_stop_loss_failure_returns_error(self, db_session):
        mock_client = MagicMock()
        mock_client.place_stop_order.side_effect = Exception("HTTP 400: Invalid timeValidity")

        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.place_stop_loss(
            ticker="VRTX_US_EQ",
            quantity=1.59,
            current_price=501.47,
            stop_loss_pct=-8.0,
        )

        assert result["status"] == "failed"
        assert "error" in result
        assert "Invalid timeValidity" in result["error"]
        orders = db_session.query(Order).filter(Order.order_type == "stop").all()
        assert len(orders) == 1
        assert orders[0].status == "failed"

    def test_place_stop_loss_below_min_order_value_still_places_protective_stop(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.place_stop_loss(
            ticker="AAPL_US_EQ",
            quantity=1.0,
            current_price=100.0,
            stop_loss_pct=-8.0,
        )

        assert result["status"] == "dry_run"
        assert result["order_type"] == "stop"
        assert db_session.query(Order).count() == 1


class TestCancelConflictingStops:
    """Tests for cancelling stop-loss orders before SELL/REDUCE."""

    @staticmethod
    def _allow_live_sell(mock_client: MagicMock) -> None:
        """Live SELL/REDUCE path clamps to get_position(); default ample shares."""
        mock_client.get_position.return_value = {"quantity": 10000.0}

    def test_sell_cancels_existing_stop(self, db_session):
        """SELL with an existing stop-loss should cancel the stop first, then SELL."""
        mock_client = MagicMock()
        self._allow_live_sell(mock_client)
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.33, "id": "stop-123"},
        ]
        mock_client.place_market_order.return_value = {"id": "sell-456", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "filled"
        mock_client.cancel_order.assert_called_once_with("stop-123")
        mock_client.place_market_order.assert_called_once()

    def test_reduce_cancels_existing_stop(self, db_session):
        """REDUCE with an existing stop-loss should cancel the stop first."""
        mock_client = MagicMock()
        self._allow_live_sell(mock_client)
        mock_client.get_pending_orders.return_value = [
            {"ticker": "AAPL_US_EQ", "type": "STOP", "stopPrice": 161.0, "id": "stop-789"},
        ]
        mock_client.place_market_order.return_value = {"id": "reduce-101", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="REDUCE",
            target_amount_gbp=600.0,
            current_price=175.0,
        )

        assert result["status"] == "filled"
        mock_client.cancel_order.assert_called_once_with("stop-789")

    def test_sell_no_existing_stop_proceeds(self, db_session):
        """SELL with no existing stop should proceed normally."""
        mock_client = MagicMock()
        self._allow_live_sell(mock_client)
        mock_client.get_pending_orders.return_value = []
        mock_client.place_market_order.return_value = {"id": "sell-111", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="MSFT_US_EQ",
            action="SELL",
            target_amount_gbp=800.0,
            current_price=400.0,
        )

        assert result["status"] == "filled"
        mock_client.cancel_order.assert_not_called()

    def test_dry_run_sell_does_not_call_t212_cancel(self, db_session):
        """Dry-run SELL should not call T212 cancel API."""
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "dry_run"
        mock_client.cancel_order.assert_not_called()
        mock_client.get_pending_orders.assert_not_called()

    def test_stop_cancel_failure_aborts_sell(self, db_session):
        """If stop cancellation fails, SELL should be aborted."""
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.33, "id": "stop-fail"},
        ]
        mock_client.cancel_order.side_effect = Exception("T212 server error")

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "failed"
        assert "failed to cancel conflicting stop-loss" in result["error"]
        mock_client.place_market_order.assert_not_called()

    def test_only_cancels_stops_for_target_ticker(self, db_session):
        """Stops for other tickers should not be cancelled."""
        mock_client = MagicMock()
        self._allow_live_sell(mock_client)
        mock_client.get_pending_orders.return_value = [
            {"ticker": "AAPL_US_EQ", "type": "STOP", "stopPrice": 161.0, "id": "stop-aapl"},
            {"ticker": "MSFT_US_EQ", "type": "STOP", "stopPrice": 380.0, "id": "stop-msft"},
        ]
        mock_client.place_market_order.return_value = {"id": "sell-222", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=175.0,
        )

        assert result["status"] == "filled"
        mock_client.cancel_order.assert_called_once_with("stop-aapl")

    def test_stop_already_triggered_treated_as_success(self, db_session):
        """If stop was already triggered (404), treat as success and proceed."""
        mock_client = MagicMock()
        self._allow_live_sell(mock_client)
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.33, "id": "stop-gone"},
        ]
        mock_client.cancel_order.side_effect = Exception("404 Not Found")
        mock_client.place_market_order.return_value = {"id": "sell-333", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "filled"
        mock_client.place_market_order.assert_called_once()

    def test_liquidate_all_cancels_stops(self, db_session):
        """liquidate_all should cancel stops before selling each position."""
        mock_client = MagicMock()
        mock_client.get_portfolio.return_value = [
            {"ticker": "AAPL_US_EQ", "quantity": 10},
        ]
        mock_client.get_pending_orders.return_value = [
            {"ticker": "AAPL_US_EQ", "type": "STOP", "stopPrice": 161.0, "id": "stop-liq"},
        ]
        mock_client.place_market_order.return_value = {"id": "liq-123", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        results = manager.liquidate_all()

        assert len(results) == 1
        assert results[0]["status"] == "filled"
        mock_client.cancel_order.assert_called_once_with("stop-liq")

    def test_buy_does_not_cancel_stops(self, db_session):
        """BUY orders should not trigger stop cancellation."""
        mock_client = MagicMock()
        mock_client.place_market_order.return_value = {"id": "buy-111", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=600.0,
            current_price=175.0,
        )

        assert result["status"] == "filled"
        mock_client.get_pending_orders.assert_not_called()
        mock_client.cancel_order.assert_not_called()

    def test_live_sell_clamps_quantity_to_broker_position(self, db_session):
        """SELL quantity must not exceed broker-reported position (avoids T212 400)."""
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = []
        mock_client.get_position.return_value = {"quantity": 1.0}
        mock_client.place_market_order.return_value = {"id": "sell-clamp", "status": "FILLED"}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "filled"
        mock_client.place_market_order.assert_called_once_with("VRTX_US_EQ", -1.0)

    def test_live_sell_zero_position_fails_before_place(self, db_session):
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = []
        mock_client.get_position.return_value = {"quantity": 0}

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.execute_market_order(
            ticker="VRTX_US_EQ",
            action="SELL",
            target_amount_gbp=600.0,
            current_price=465.0,
        )

        assert result["status"] == "failed"
        assert "No shares available" in result["error"]
        mock_client.place_market_order.assert_not_called()

    def test_cancel_updates_local_db_record(self, db_session):
        """After cancelling a stop on T212, the local Order record should be updated."""
        # Pre-create a pending stop order in DB
        stop_order = Order(
            ticker="VRTX_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-0.55,
            stop_price=431.33,
            t212_order_id="stop-db-123",
            status="pending",
        )
        db_session.add(stop_order)
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.33, "id": "stop-db-123"},
        ]

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_conflicting_stops("VRTX_US_EQ")

        assert result["status"] == "ok"
        assert "stop-db-123" in result["cancelled"]

        # Verify DB was updated
        db_session.expire_all()
        updated = db_session.query(Order).filter(Order.t212_order_id == "stop-db-123").first()
        assert updated.status == "cancelled"


class TestT212TimeValidityMapping:
    """T212 API requires GOOD_TILL_CANCEL, not GTC."""

    def test_t212_client_sends_good_till_cancel_for_stop_order(self):
        """When place_stop_order is called with time_validity='GTC', HTTP body uses GOOD_TILL_CANCEL."""
        mock_settings = MagicMock()
        mock_settings.t212_base_url = "https://demo.trading212.com/api/v0"
        mock_settings.t212_api_key = "test-key"
        mock_settings.t212_api_secret = "test-secret"
        with patch("src.agents.execution.t212_client.get_session"), patch(
            "src.agents.execution.t212_client.get_settings", return_value=mock_settings
        ), patch("httpx.Client") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"id": 1, "status": "NEW"}
            mock_response.text = '{"id":1,"status":"NEW"}'
            mock_response.headers = {}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response

            client = T212Client()
            client.place_stop_order(
                ticker="AAPL_US_EQ",
                quantity=-5.0,
                stop_price=161.0,
                time_validity="GTC",
            )

            call_args = mock_client_instance.request.call_args
            body = call_args[1].get("json") or {}
            assert body.get("timeValidity") == "GOOD_TILL_CANCEL"


class TestT212EmptyResponseBody:
    """T212 DELETE /equity/orders/{id} returns 200 with empty body."""

    def test_request_handles_empty_body_200(self):
        """_request should return {} when T212 responds 200 with empty body."""
        mock_settings = MagicMock()
        mock_settings.t212_base_url = "https://demo.trading212.com/api/v0"
        mock_settings.t212_api_key = "test-key"
        mock_settings.t212_api_secret = "test-secret"
        with patch("src.agents.execution.t212_client.get_session"), patch(
            "src.agents.execution.t212_client.get_settings", return_value=mock_settings
        ), patch("httpx.Client") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = ""  # Empty body — the root cause
            mock_response.headers = {}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response

            client = T212Client()
            result = client.cancel_order("46150111089")

            assert result == {}
            # Should NOT have called .json() on empty body
            mock_response.json.assert_not_called()

    def test_request_handles_whitespace_only_body(self):
        """_request should return {} when T212 responds with whitespace-only body."""
        mock_settings = MagicMock()
        mock_settings.t212_base_url = "https://demo.trading212.com/api/v0"
        mock_settings.t212_api_key = "test-key"
        mock_settings.t212_api_secret = "test-secret"
        with patch("src.agents.execution.t212_client.get_session"), patch(
            "src.agents.execution.t212_client.get_settings", return_value=mock_settings
        ), patch("httpx.Client") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "  \n  "  # Whitespace only
            mock_response.headers = {}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response

            client = T212Client()
            result = client.cancel_order("12345")

            assert result == {}
            mock_response.json.assert_not_called()

    def test_request_parses_json_when_body_present(self):
        """_request should parse JSON normally when body is present."""
        mock_settings = MagicMock()
        mock_settings.t212_base_url = "https://demo.trading212.com/api/v0"
        mock_settings.t212_api_key = "test-key"
        mock_settings.t212_api_secret = "test-secret"
        with patch("src.agents.execution.t212_client.get_session"), patch(
            "src.agents.execution.t212_client.get_settings", return_value=mock_settings
        ), patch("httpx.Client") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '{"id": 123, "status": "FILLED"}'
            mock_response.headers = {}
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"id": 123, "status": "FILLED"}

            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response

            client = T212Client()
            result = client.place_market_order("AAPL_US_EQ", 1.0)

            assert result == {"id": 123, "status": "FILLED"}
            mock_response.json.assert_called_once()


class TestRetryPredicate:
    """_is_retryable should only retry transient errors."""

    def test_429_is_retryable(self):
        resp = MagicMock()
        resp.status_code = 429
        exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is True

    def test_500_is_retryable(self):
        resp = MagicMock()
        resp.status_code = 500
        exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is True

    def test_502_is_retryable(self):
        resp = MagicMock()
        resp.status_code = 502
        exc = httpx.HTTPStatusError("bad gateway", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is True

    def test_404_is_not_retryable(self):
        resp = MagicMock()
        resp.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is False

    def test_400_is_not_retryable(self):
        resp = MagicMock()
        resp.status_code = 400
        exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is False

    def test_422_is_not_retryable(self):
        resp = MagicMock()
        resp.status_code = 422
        exc = httpx.HTTPStatusError("unprocessable", request=MagicMock(), response=resp)
        assert _is_retryable(exc) is False

    def test_network_error_is_retryable(self):
        exc = httpx.ConnectError("connection refused")
        assert _is_retryable(exc) is True

    def test_timeout_is_retryable(self):
        exc = httpx.ReadTimeout("timeout")
        assert _is_retryable(exc) is True


class TestCancelConflictingStopsRetryError:
    """cancel_conflicting_stops should unwrap RetryError wrapping a 404."""

    @pytest.fixture(autouse=True)
    def mock_get_session(self, db_session):
        with patch("src.agents.execution.order_manager.get_session", return_value=db_session):
            yield

    def test_retryerror_wrapping_404_treated_as_success(self, db_session):
        """When cancel_order raises RetryError whose last attempt was a 404,
        cancel_conflicting_stops should treat the stop as already gone."""
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.0, "id": "stop-999"},
        ]

        # Build a RetryError wrapping an HTTPStatusError with 404
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.text = '{"detail":"Order not found"}'
        inner_exc = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=resp_404
        )
        # tenacity RetryError needs a last_attempt Future
        future = Future(1)
        future.set_exception(inner_exc)
        retry_error = RetryError(future)

        mock_client.cancel_order.side_effect = retry_error

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_conflicting_stops("VRTX_US_EQ")

        assert result["status"] == "ok"
        assert "stop-999" in result["cancelled"]

    def test_retryerror_wrapping_non_404_treated_as_failure(self, db_session):
        """When cancel_order raises RetryError wrapping a 500, it should fail."""
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.0, "id": "stop-888"},
        ]

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"
        inner_exc = httpx.HTTPStatusError(
            "500 Internal Server Error", request=MagicMock(), response=resp_500
        )
        future = Future(1)
        future.set_exception(inner_exc)
        retry_error = RetryError(future)

        mock_client.cancel_order.side_effect = retry_error

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_conflicting_stops("VRTX_US_EQ")

        assert result["status"] == "failed"
        assert "stop-888" in result["error"]

    def test_httpstatus_400_order_not_found_body_treated_as_success(self, db_session):
        """400 with not-found style body should be idempotent (stop already gone)."""
        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"ticker": "VRTX_US_EQ", "type": "STOP", "stopPrice": 431.0, "id": "stop-400nf"},
        ]
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = '{"detail":"Order not found"}'
        mock_client.cancel_order.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=resp_400
        )

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_conflicting_stops("VRTX_US_EQ")

        assert result["status"] == "ok"
        assert "stop-400nf" in result["cancelled"]


class TestPendingStopReconciliation:
    """Reconcile local pending stop rows against live T212 pending orders."""

    @pytest.fixture(autouse=True)
    def mock_get_session(self, db_session):
        with patch("src.agents.execution.order_manager.get_session", return_value=db_session):
            yield

    def test_reconcile_marks_stale_pending_stops_cancelled(self, db_session):
        db_session.add_all([
            Order(
                ticker="AAPL_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-1.0,
                stop_price=100.0,
                t212_order_id="live-1",
                status="pending",
            ),
            Order(
                ticker="MSFT_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-1.0,
                stop_price=200.0,
                t212_order_id="stale-1",
                status="pending",
            ),
        ])
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"id": "live-1", "ticker": "AAPL_US_EQ", "type": "STOP"},
        ]

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.reconcile_pending_stop_orders_with_t212()

        assert result["pending_local_count"] == 2
        assert result["pending_live_count"] == 1
        assert result["stale_pending_count"] == 1
        assert result["reconciled_pending_count"] == 1
        assert result["live_fetch_error"] is None

        db_session.expire_all()
        stale = db_session.query(Order).filter(Order.t212_order_id == "stale-1").first()
        assert stale.status == "cancelled"
        assert "Reconciled" in (stale.error_message or "")

    def test_reconcile_returns_live_fetch_error_fail_open(self, db_session):
        db_session.add(
            Order(
                ticker="AAPL_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-1.0,
                stop_price=100.0,
                t212_order_id="live-1",
                status="pending",
            )
        )
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.side_effect = RuntimeError("rate limited")

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.reconcile_pending_stop_orders_with_t212()

        assert result["pending_local_count"] == 1
        assert result["pending_live_count"] == 0
        assert result["reconciled_pending_count"] == 0
        assert "rate limited" in (result["live_fetch_error"] or "")


class TestOrderHistorySync:
    """Sync local pending rows against T212 history terminal statuses."""

    @pytest.fixture(autouse=True)
    def mock_get_session(self, db_session):
        with patch("src.agents.execution.order_manager.get_session", return_value=db_session):
            yield

    def test_sync_orders_maps_terminal_t212_statuses(self, db_session):
        db_session.add_all([
            Order(
                ticker="AAPL_US_EQ",
                action="BUY",
                order_type="market",
                quantity=1.0,
                t212_order_id="fill-1",
                status="pending",
            ),
            Order(
                ticker="MSFT_US_EQ",
                action="SELL",
                order_type="market",
                quantity=-1.0,
                t212_order_id="cancel-1",
                status="pending",
            ),
            Order(
                ticker="NVDA_US_EQ",
                action="BUY",
                order_type="limit",
                quantity=1.0,
                t212_order_id="reject-1",
                status="pending",
            ),
        ])
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_order_history.return_value = {
            "items": [
                {"order": {"id": "fill-1", "status": "FILLED", "filledQuantity": 1.0, "filledValue": 150.0}},
                {"order": {"id": "cancel-1", "status": "CANCELLED"}},
                {"order": {"id": "reject-1", "status": "REJECTED"}},
            ],
            "nextPagePath": None,
        }
        mock_client.get_pending_orders.return_value = []

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.sync_orders_with_t212()

        assert result["filled_count"] == 1
        assert result["cancelled_count"] == 1
        assert result["failed_count"] == 1
        assert result["updated_total"] == 3

        db_session.expire_all()
        assert db_session.query(Order).filter(Order.t212_order_id == "fill-1").first().status == "filled"
        assert db_session.query(Order).filter(Order.t212_order_id == "cancel-1").first().status == "cancelled"
        assert db_session.query(Order).filter(Order.t212_order_id == "reject-1").first().status == "failed"


class TestPendingMarketSellCancellation:
    """Cancel stale pending market SELL rows when a newer cycle decides HOLD/QUEUED."""

    @pytest.fixture(autouse=True)
    def mock_get_session(self, db_session):
        with patch("src.agents.execution.order_manager.get_session", return_value=db_session):
            yield

    def test_cancel_pending_market_sells_cancels_live_matching_rows(self, db_session):
        db_session.add_all([
            Order(
                ticker="ORCL_US_EQ",
                action="SELL",
                order_type="market",
                quantity=-3.71,
                t212_order_id="sell-live-1",
                status="pending",
            ),
            Order(
                ticker="ORCL_US_EQ",
                action="SELL",
                order_type="market",
                quantity=-1.0,
                t212_order_id="sell-stale-1",
                status="pending",
            ),
        ])
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"id": "sell-live-1", "ticker": "ORCL_US_EQ", "type": "MARKET"},
        ]

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_pending_market_sells(
            "ORCL_US_EQ",
            "Cancelled after newer HOLD decision in cycle scheduled_20260326_120000",
        )

        assert result["status"] == "ok"
        assert result["cancelled"] == ["sell-live-1"]
        mock_client.cancel_order.assert_called_once_with("sell-live-1")

        db_session.expire_all()
        cancelled = db_session.query(Order).filter(Order.t212_order_id == "sell-live-1").one()
        untouched = db_session.query(Order).filter(Order.t212_order_id == "sell-stale-1").one()
        assert cancelled.status == "cancelled"
        assert "newer HOLD decision" in (cancelled.error_message or "")
        assert untouched.status == "pending"

    def test_cancel_pending_market_sells_fail_open_when_live_fetch_fails(self, db_session):
        db_session.add(
            Order(
                ticker="ORCL_US_EQ",
                action="SELL",
                order_type="market",
                quantity=-3.71,
                t212_order_id="sell-live-1",
                status="pending",
            )
        )
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.side_effect = RuntimeError("rate limited")

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_pending_market_sells(
            "ORCL_US_EQ",
            "Cancelled after newer HOLD decision in cycle scheduled_20260326_120000",
        )

        assert result["status"] == "failed"
        assert "rate limited" in result["error"]


class TestCancelPendingOrdersByClass:
    """Generic cancel runner helper for Slack cancel commands."""

    @pytest.fixture(autouse=True)
    def mock_get_session(self, db_session):
        with patch("src.agents.execution.order_manager.get_session", return_value=db_session):
            yield

    def test_cancel_pending_orders_by_class_matches_buy_and_stop_sell(self, db_session):
        db_session.add_all([
            Order(
                ticker="NVDA_US_EQ",
                action="BUY",
                order_type="market",
                quantity=2.0,
                t212_order_id="buy-1",
                status="pending",
            ),
            Order(
                ticker="NVDA_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-2.0,
                t212_order_id="stop-1",
                status="pending",
            ),
        ])
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"id": "buy-1", "ticker": "NVDA_US_EQ", "type": "MARKET", "quantity": 2.0},
            {"id": "stop-1", "ticker": "NVDA_US_EQ", "type": "STOP", "quantity": -2.0, "stopPrice": 120.0},
        ]

        manager = OrderManager(client=mock_client, dry_run=False)
        buy_result = manager.cancel_pending_orders_by_class(
            tickers=["NVDA_US_EQ"],
            order_class="buy",
            reason="cancel buy via Slack",
        )
        stop_result = manager.cancel_pending_orders_by_class(
            tickers=["NVDA_US_EQ"],
            order_class="stop_sell",
            reason="cancel stop sell via Slack",
        )

        assert buy_result["status"] == "ok"
        assert buy_result["cancelled"] == ["buy-1"]
        assert stop_result["status"] == "ok"
        assert stop_result["cancelled"] == ["stop-1"]

    def test_cancel_pending_orders_by_class_returns_partial_on_mixed_failures(self, db_session):
        db_session.add_all([
            Order(
                ticker="NVDA_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-2.0,
                t212_order_id="stop-1",
                status="pending",
            ),
            Order(
                ticker="MSFT_US_EQ",
                action="SELL",
                order_type="stop",
                quantity=-1.0,
                t212_order_id="stop-2",
                status="pending",
            ),
        ])
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_pending_orders.return_value = [
            {"id": "stop-1", "ticker": "NVDA_US_EQ", "type": "STOP", "quantity": -2.0, "stopPrice": 120.0},
            {"id": "stop-2", "ticker": "MSFT_US_EQ", "type": "STOP", "quantity": -1.0, "stopPrice": 200.0},
        ]

        def cancel_side_effect(order_id: str):
            if order_id == "stop-2":
                raise RuntimeError("broker error")
            return {}

        mock_client.cancel_order.side_effect = cancel_side_effect

        manager = OrderManager(client=mock_client, dry_run=False)
        result = manager.cancel_pending_orders_by_class(
            tickers=["NVDA_US_EQ", "MSFT_US_EQ"],
            order_class="stop_sell",
            reason="cancel stop sell via Slack",
        )

        assert result["status"] == "partial"
        assert result["cancelled"] == ["stop-1"]
        assert len(result["failures"]) == 1
        assert result["failures"][0]["order_id"] == "stop-2"


class TestFxAwareQuantity:
    """Tests for price_gbp / fx-aware quantity calculation in execute_market_order."""

    def test_buy_with_price_gbp_uses_gbp_for_quantity(self, db_session):
        """BUY quantity prefers whole shares while still using price_gbp for sizing."""
        manager = OrderManager(client=MagicMock(), dry_run=True)
        # USD price $232, GBP equivalent £179 (≈ GBP/USD 0.772)
        result = manager.execute_market_order(
            ticker="MPC_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=232.0,  # USD (native)
            price_gbp=179.0,      # GBP equivalent
        )
        # 3 shares would cost £537 (>5% overspend), so the whole-share policy uses 2.
        assert result["status"] == "dry_run"
        assert result["quantity"] == 2.0
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        # value_gbp for BUY always uses target_amount_gbp regardless of price_gbp
        assert orders[0].value_gbp == 500.0

    def test_buy_without_price_gbp_falls_back_to_current_price(self, db_session):
        """When price_gbp is not provided, current_price is used with the whole-share policy."""
        manager = OrderManager(client=MagicMock(), dry_run=True)
        result = manager.execute_market_order(
            ticker="MPC_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=232.0,
        )
        assert result["quantity"] == 2.0

    def test_buy_fractional_fallback_when_no_whole_share_fits_policy(self, db_session):
        manager = OrderManager(client=MagicMock(), dry_run=True)

        result = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=900.0,
        )

        assert result["status"] == "dry_run"
        assert result["quantity"] == 0.55

    def test_sell_with_price_gbp_uses_gbp_for_value_logging(self, db_session):
        """SELL value_gbp is logged using price_gbp when provided."""
        mock_client = MagicMock()
        mock_client.get_position.return_value = {"quantity": 2.79}
        mock_client.place_market_order.return_value = {"id": "order-1"}
        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.execute_market_order(
            ticker="MPC_US_EQ",
            action="SELL",
            target_amount_gbp=500.0,
            current_price=232.0,  # USD
            price_gbp=179.0,      # GBP
        )
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        # value_gbp = 2.79 × £179 = £499.41
        assert abs(orders[0].value_gbp - 2.79 * 179.0) < 0.01

    def test_place_stop_loss_value_gbp_uses_current_price_gbp(self, db_session):
        """Stop-loss value_gbp is logged in GBP when current_price_gbp is provided."""
        mock_client = MagicMock()
        mock_client.place_stop_order.return_value = {"id": "stop-1"}
        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.place_stop_loss(
            ticker="MPC_US_EQ",
            quantity=2.79,
            current_price=232.0,       # USD — used for stop price to T212
            stop_loss_pct=-8.0,
            current_price_gbp=179.0,   # GBP — used for value_gbp logging
        )
        assert result["status"] == "placed"
        orders = db_session.query(Order).all()
        assert len(orders) == 1
        # stop_order_value = 2.79 × £179 = £499.41
        assert abs(orders[0].value_gbp - 2.79 * 179.0) < 0.01
        # stop_price sent to T212 should use native USD price: 232 × 0.92 = 213.44
        mock_client.place_stop_order.assert_called_once()
        call_kwargs = mock_client.place_stop_order.call_args
        assert abs(call_kwargs.kwargs.get("stop_price", 0) - round(232.0 * 0.92, 2)) < 0.01

    def test_place_stop_loss_http_failure_includes_response_body(self, db_session):
        mock_client = MagicMock()
        response = MagicMock()
        response.status_code = 400
        response.text = '{"detail":"Reserved shares conflict"}'
        mock_client.place_stop_order.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=response,
        )
        manager = OrderManager(client=mock_client, dry_run=False)

        result = manager.place_stop_loss(
            ticker="MPC_US_EQ",
            quantity=2.79,
            current_price=232.0,
            stop_loss_pct=-8.0,
            current_price_gbp=179.0,
        )

        assert result["status"] == "failed"
        assert "HTTP 400" in result["error"]
        assert "Reserved shares conflict" in result["error"]

    def test_place_stop_loss_stop_price_remains_native_currency(self, db_session):
        """Stop trigger price sent to T212 always uses native current_price, not price_gbp."""
        mock_client = MagicMock()
        mock_client.place_stop_order.return_value = {"id": "stop-2"}
        manager = OrderManager(client=mock_client, dry_run=False)

        manager.place_stop_loss(
            ticker="MPC_US_EQ",
            quantity=2.0,
            current_price=200.0,      # USD
            stop_loss_pct=-8.0,
            current_price_gbp=155.0,  # GBP — must NOT affect stop trigger price
        )
        call_kwargs = mock_client.place_stop_order.call_args
        # Stop price must be 200 × 0.92 = 184.0 USD, not 155 × 0.92 = 142.6 GBP
        assert call_kwargs.kwargs.get("stop_price") == round(200.0 * 0.92, 2)
