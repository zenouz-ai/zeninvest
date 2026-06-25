"""Tests for the time-bounded BUY denial list (P4-4, US-7.5)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.agents.execution import instrument_denylist as dl
from src.agents.execution.order_manager import OrderManager
from src.data.database import SessionLocal, engine
from src.data.models import Base, HaltedInstrument


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    s.query(HaltedInstrument).delete()
    s.commit()
    s.close()
    yield
    s = SessionLocal()
    s.query(HaltedInstrument).delete()
    s.commit()
    s.close()


def test_record_then_halted():
    dl.record_rejection("AAPL_US_EQ", 400, "t212_buy_rejected_400")
    assert dl.is_halted("AAPL_US_EQ") is True
    assert dl.is_halted("MSFT_US_EQ") is False


def test_record_extends_and_increments_hit_count():
    dl.record_rejection("AAPL_US_EQ", 400, "r1")
    dl.record_rejection("AAPL_US_EQ", 403, "r2")
    s = SessionLocal()
    try:
        row = s.query(HaltedInstrument).filter_by(ticker="AAPL_US_EQ").one()
        assert row.hit_count == 2
        assert row.status_code == 403
    finally:
        s.close()


def test_expired_halt_is_not_active():
    dl.record_rejection("AAPL_US_EQ", 400, "r")
    s = SessionLocal()
    try:
        row = s.query(HaltedInstrument).filter_by(ticker="AAPL_US_EQ").one()
        row.halted_until = datetime.now(timezone.utc) - timedelta(hours=1)
        s.commit()
    finally:
        s.close()
    assert dl.is_halted("AAPL_US_EQ") is False
    assert dl.active_halt_count() == 0


def test_clear_and_clear_expired():
    dl.record_rejection("AAPL_US_EQ", 400, "r")
    assert dl.clear("AAPL_US_EQ") is True
    assert dl.clear("AAPL_US_EQ") is False

    dl.record_rejection("MSFT_US_EQ", 400, "r")
    s = SessionLocal()
    try:
        row = s.query(HaltedInstrument).filter_by(ticker="MSFT_US_EQ").one()
        row.halted_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    finally:
        s.close()
    assert dl.clear_expired() == 1


def test_disabled_feature_records_nothing_and_never_halts(monkeypatch):
    monkeypatch.setattr(
        "src.agents.execution.instrument_denylist.get_settings",
        lambda: MagicMock(instrument_denylist_enabled=False, instrument_denylist_ttl_hours=24),
    )
    dl.record_rejection("AAPL_US_EQ", 400, "r")
    assert dl.is_halted("AAPL_US_EQ") is False
    s = SessionLocal()
    try:
        assert s.query(HaltedInstrument).count() == 0
    finally:
        s.close()


def test_execute_market_order_skips_halted_buy():
    """A halted ticker short-circuits a BUY before any broker call."""
    dl.record_rejection("AAPL_US_EQ", 400, "t212_buy_rejected_400")
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

    assert result["status"] == "skipped"
    assert result["reason"] == "instrument_halted"
    mock_client.place_market_order.assert_not_called()


def test_non_halted_buy_not_skipped_by_denylist():
    """A clean ticker is not short-circuited (dry-run path proceeds)."""
    mock_client = MagicMock()
    manager = OrderManager(client=mock_client, dry_run=True)

    result = manager.execute_market_order(
        ticker="MSFT_US_EQ",
        action="BUY",
        target_amount_gbp=525.0,
        current_price=175.0,
        strategy="momentum",
        conviction=80,
    )

    assert result["status"] == "dry_run"
