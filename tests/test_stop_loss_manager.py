"""Tests for StopLossManager — reassessment, trailing stops, and limit orders."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, Order, StopLossAdjustment
from src.agents.execution.order_manager import OrderManager
from src.agents.execution.stop_loss_manager import StopLossManager


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    """Patch get_session in all modules that use it."""
    with patch("src.agents.execution.order_manager.get_session", return_value=db_session), \
         patch("src.agents.execution.stop_loss_manager.get_session", return_value=db_session):
        yield


@pytest.fixture
def mock_settings():
    """Settings with order management enabled."""
    settings = MagicMock()
    settings.order_management_enabled = True
    settings.reassess_stops_enabled = True
    settings.trailing_stops_enabled = True
    settings.trailing_stop_default_trail_pct = 5.0
    settings.limit_orders_enabled = True
    settings.limit_order_default_offset_pct = 2.0
    settings.limit_order_time_validity = "GTC"
    settings.min_order_value_gbp = 500.0
    settings.atr_multiplier = 2.0
    settings.min_stop_distance_pct = 3.0
    settings.max_stop_distance_pct = 15.0
    settings.only_tighten_stops = True
    return settings


@pytest.fixture
def manager(mock_settings):
    """StopLossManager with mocked client and settings."""
    mock_client = MagicMock()
    mock_client.get_pending_orders.return_value = []
    order_manager = OrderManager(client=mock_client, dry_run=True)

    with patch("src.agents.execution.stop_loss_manager.get_settings", return_value=mock_settings):
        slm = StopLossManager(
            order_manager=order_manager,
            client=mock_client,
            dry_run=True,
        )
        slm.settings = mock_settings
        yield slm


class TestComputeVolatilityStop:
    def test_basic_atr_stop(self, manager):
        # Price=100, ATR=5, multiplier=2 -> raw distance=10 -> 10% -> stop=90
        stop = manager._compute_volatility_stop(100.0, 5.0)
        assert stop == 90.0

    def test_clamped_to_min(self, manager):
        # Price=100, ATR=0.5, multiplier=2 -> raw distance=1 -> 1% -> clamped to min 3% -> stop=97
        stop = manager._compute_volatility_stop(100.0, 0.5)
        assert stop == 97.0

    def test_clamped_to_max(self, manager):
        # Price=100, ATR=20, multiplier=2 -> raw distance=40 -> 40% -> clamped to max 15% -> stop=85
        stop = manager._compute_volatility_stop(100.0, 20.0)
        assert stop == 85.0

    def test_mid_range_atr(self, manager):
        # Price=200, ATR=8, multiplier=2 -> raw distance=16 -> 8% -> within bounds -> stop=184
        stop = manager._compute_volatility_stop(200.0, 8.0)
        assert stop == 184.0


class TestReassessStops:
    def test_no_op_when_disabled(self, manager):
        manager.settings.reassess_stops_enabled = False
        results = manager.reassess_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 175.0}],
            stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"atr_14": 5.0}}],
        )
        assert results == []

    def test_skips_position_without_atr(self, manager, db_session):
        results = manager.reassess_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 175.0}],
            stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {}}],
        )
        assert results == []

    def test_reassess_places_new_stop(self, manager, db_session):
        # No existing stop, ATR=5, price=100 -> stop at 90 (10%)
        results = manager.reassess_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 100.0}],
            stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"atr_14": 5.0}}],
            cycle_id="test_cycle_1",
        )
        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL_US_EQ"
        assert results[0]["new_stop_price"] == 90.0
        assert results[0]["adjustment_type"] == "reassess"

        # Check DB audit trail
        adjustments = db_session.query(StopLossAdjustment).all()
        assert len(adjustments) == 1
        assert adjustments[0].ticker == "AAPL_US_EQ"
        assert adjustments[0].new_stop_price == 90.0

    def test_only_tighten_skips_lower_stop(self, manager, db_session):
        # Existing stop at 95, new would be 90 -> skip (only tighten)
        # Seed a pending stop in DB
        db_session.add(Order(
            timestamp=datetime.now(timezone.utc),
            ticker="AAPL_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-10,
            stop_price=95.0,
            status="dry_run",
            t212_order_id="old-stop-123",
        ))
        db_session.commit()

        results = manager.reassess_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 100.0}],
            stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"atr_14": 5.0}}],
        )
        assert len(results) == 0

    def test_tightens_stop_when_new_is_higher(self, manager, db_session):
        # Existing stop at 80, price=100, ATR=2, mult=2 -> distance=4 -> 4% -> stop=96
        db_session.add(Order(
            timestamp=datetime.now(timezone.utc),
            ticker="AAPL_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-10,
            stop_price=80.0,
            status="dry_run",
            t212_order_id="old-stop-456",
        ))
        db_session.commit()

        results = manager.reassess_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 100.0}],
            stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"atr_14": 2.0}}],
            cycle_id="test_tighten",
        )
        assert len(results) == 1
        assert results[0]["new_stop_price"] == 96.0
        assert results[0]["old_stop_price"] == 80.0


class TestTrailingStops:
    def test_no_op_when_disabled(self, manager):
        manager.settings.trailing_stops_enabled = False
        results = manager.apply_trailing_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 175.0}],
        )
        assert results == []

    def test_initial_trailing_stop(self, manager, db_session):
        # No previous HWM, price=100, trail=5% -> stop at 95
        results = manager.apply_trailing_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 100.0}],
            cycle_id="trail_1",
        )
        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL_US_EQ"
        assert results[0]["new_stop_price"] == 95.0
        assert results[0]["high_water_mark"] == 100.0

    def test_trailing_ratchet_up(self, manager, db_session):
        # Seed previous HWM of 100, now price is 110 -> new HWM=110, stop=104.5
        db_session.add(StopLossAdjustment(
            timestamp=datetime.now(timezone.utc),
            ticker="AAPL_US_EQ",
            adjustment_type="trailing",
            high_water_mark=100.0,
            new_stop_price=95.0,
            status="dry_run",
        ))
        db_session.commit()

        results = manager.apply_trailing_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 110.0}],
            cycle_id="trail_2",
        )
        assert len(results) == 1
        assert results[0]["new_stop_price"] == 104.5
        assert results[0]["high_water_mark"] == 110.0

    def test_no_ratchet_down(self, manager, db_session):
        # Previous HWM=110, price dropped to 105 -> HWM stays 110, stop stays 104.5
        # Existing stop at 104.5
        db_session.add(StopLossAdjustment(
            timestamp=datetime.now(timezone.utc),
            ticker="AAPL_US_EQ",
            adjustment_type="trailing",
            high_water_mark=110.0,
            new_stop_price=104.5,
            status="dry_run",
        ))
        db_session.add(Order(
            timestamp=datetime.now(timezone.utc),
            ticker="AAPL_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-10,
            stop_price=104.5,
            status="dry_run",
        ))
        db_session.commit()

        results = manager.apply_trailing_stops(
            positions=[{"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 105.0}],
            cycle_id="trail_3",
        )
        # HWM=110, trail=5% -> stop=104.5, same as existing -> no ratchet
        assert len(results) == 0


class TestLimitBuy:
    def test_no_op_when_disabled(self, manager):
        manager.settings.limit_orders_enabled = False
        result = manager.place_limit_buy(
            ticker="AAPL_US_EQ",
            target_amount_gbp=500.0,
            current_price=175.0,
        )
        assert result["status"] == "skipped"

    def test_dry_run_limit_buy(self, manager, db_session):
        result = manager.place_limit_buy(
            ticker="AAPL_US_EQ",
            target_amount_gbp=510.0,
            current_price=100.0,
            offset_pct=2.0,
            strategy="momentum",
            conviction=80,
            cycle_id="limit_1",
        )
        assert result["status"] == "dry_run"
        assert result["order_type"] == "limit"
        assert result["limit_price"] == 98.0  # 100 * (1 - 2/100) = 98
        assert result["quantity"] > 0

        # Check order logged
        orders = db_session.query(Order).filter(Order.order_type == "limit").all()
        assert len(orders) == 1
        assert orders[0].limit_price == 98.0

        # Check adjustment logged
        adj = db_session.query(StopLossAdjustment).filter(
            StopLossAdjustment.adjustment_type == "limit_order"
        ).all()
        assert len(adj) == 1

    def test_uses_config_default_offset(self, manager, db_session):
        manager.settings.limit_order_default_offset_pct = 3.0
        result = manager.place_limit_buy(
            ticker="MSFT_US_EQ",
            target_amount_gbp=1000.0,
            current_price=200.0,
        )
        assert result["limit_price"] == 194.0  # 200 * (1 - 3/100) = 194

    def test_zero_quantity_skipped(self, manager, db_session):
        result = manager.place_limit_buy(
            ticker="BRK.A_US_EQ",
            target_amount_gbp=1.0,
            current_price=500000.0,
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "zero_quantity"

    def test_below_min_order_value_skipped_and_not_logged(self, manager, db_session):
        result = manager.place_limit_buy(
            ticker="AAPL_US_EQ",
            target_amount_gbp=100.0,
            current_price=100.0,
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "below_min_order_value"
        assert db_session.query(Order).filter(Order.order_type == "limit").count() == 0


class TestExtractAtr:
    def test_extracts_atr_14(self):
        assert StopLossManager._extract_atr({"indicators": {"atr_14": 5.5}}) == 5.5

    def test_extracts_atr_fallback(self):
        assert StopLossManager._extract_atr({"indicators": {"atr": 3.2}}) == 3.2

    def test_returns_none_when_missing(self):
        assert StopLossManager._extract_atr({"indicators": {}}) is None

    def test_returns_none_when_invalid(self):
        assert StopLossManager._extract_atr({"indicators": {"atr_14": "bad"}}) is None

    def test_returns_none_on_empty_data(self):
        assert StopLossManager._extract_atr({}) is None


class TestSettingsProperties:
    """Test the new order management Settings properties."""

    def test_defaults_when_section_missing(self):
        from src.utils.config import Settings
        settings = Settings(config={"trading": {}, "risk": {}, "strategy": {},
                                     "moderation": {}, "models": {}, "data_providers": {},
                                     "cost_limits": {"anthropic_daily_gbp": 1, "openai_daily_gbp": 1,
                                                     "google_daily_gbp": 1, "total_monthly_gbp": 50,
                                                     "alert_threshold_pct": 80}})
        assert settings.order_management_enabled is False
        assert settings.reassess_stops_enabled is False
        assert settings.trailing_stops_enabled is False
        assert settings.trailing_stop_default_trail_pct == 5.0
        assert settings.limit_orders_enabled is False
        assert settings.limit_order_default_offset_pct == 2.0
        assert settings.limit_order_time_validity == "GTC"
        assert settings.atr_multiplier == 2.0
        assert settings.min_stop_distance_pct == 3.0
        assert settings.max_stop_distance_pct == 15.0
        assert settings.only_tighten_stops is True

    def test_reads_from_config(self):
        from src.utils.config import Settings
        settings = Settings(config={
            "trading": {}, "risk": {}, "strategy": {},
            "moderation": {}, "models": {}, "data_providers": {},
            "cost_limits": {"anthropic_daily_gbp": 1, "openai_daily_gbp": 1,
                            "google_daily_gbp": 1, "total_monthly_gbp": 50,
                            "alert_threshold_pct": 80},
            "order_management": {
                "enabled": True,
                "reassess_stops": True,
                "trailing_stops": {"enabled": True, "default_trail_pct": 8.0},
                "limit_orders": {"enabled": True, "default_offset_pct": 3.5, "time_validity": "DAY"},
                "atr_multiplier": 1.5,
                "min_stop_distance_pct": 2.0,
                "max_stop_distance_pct": 20.0,
                "only_tighten_stops": False,
            },
        })
        assert settings.order_management_enabled is True
        assert settings.reassess_stops_enabled is True
        assert settings.trailing_stops_enabled is True
        assert settings.trailing_stop_default_trail_pct == 8.0
        assert settings.limit_orders_enabled is True
        assert settings.limit_order_default_offset_pct == 3.5
        assert settings.limit_order_time_validity == "DAY"
        assert settings.atr_multiplier == 1.5
        assert settings.min_stop_distance_pct == 2.0
        assert settings.max_stop_distance_pct == 20.0
        assert settings.only_tighten_stops is False
