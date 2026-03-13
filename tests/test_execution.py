"""Tests for the execution agent — T212 client and order manager."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, Order

try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None
from src.agents.execution.t212_client import (
    T212Client,
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

        with patch("src.agents.execution.t212_client.get_session"), patch(
            "httpx.Client"
        ) as mock_client_class, patch.object(T212Client, "_check_rate_limit"):
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
            target_amount_gbp=500.0,
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

    def test_duplicate_detection(self, db_session):
        mock_client = MagicMock()
        manager = OrderManager(client=mock_client, dry_run=True)

        # First order
        result1 = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=175.0,
        )
        assert result1["status"] == "dry_run"

        # Same order again (should be duplicate)
        result2 = manager.execute_market_order(
            ticker="AAPL_US_EQ",
            action="BUY",
            target_amount_gbp=500.0,
            current_price=175.0,
        )
        assert result2["status"] == "skipped"
        assert result2["reason"] == "duplicate"

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
            target_amount_gbp=500.0,
            current_price=150.0,
        )

        assert result["status"] == "failed"
        assert "API error" in result["error"]

        orders = db_session.query(Order).all()
        assert len(orders) == 1
        assert orders[0].status == "failed"

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
        mock_client.place_market_order.return_value = {"id": "liquidation-123"}

        manager = OrderManager(client=mock_client, dry_run=False)
        results = manager.liquidate_all()

        assert len(results) == 2
        assert all(r["status"] == "sold" for r in results)
        assert mock_client.place_market_order.call_count == 2

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
