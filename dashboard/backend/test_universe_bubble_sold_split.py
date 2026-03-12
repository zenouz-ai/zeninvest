import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.backend.app.routers.universe import get_universe_bubble
from dashboard.backend.app.schemas import UniverseBubbleSchema
from src.data.models import Base, Instrument, Order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_universe_bubble_sold_split_live_vs_dry_run(monkeypatch):
    session = _make_session()

    # Single instrument
    inst = Instrument(
        ticker="TEST_US_EQ",
        name="Test Corp",
        sector="Test",
        industry="Test",
        market_cap=1_000_000.0,
        last_screened_at=datetime.now(timezone.utc),
        data_available=True,
    )
    session.add(inst)

    # Live SELL: -2.0, dry-run SELL: -1.5 -> totals should be 3.5
    live_sell = Order(
        ticker="TEST_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-2.0,
        status="filled",
    )
    dry_run_sell = Order(
        ticker="TEST_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-1.5,
        status="dry_run",
    )
    session.add_all([live_sell, dry_run_sell])
    session.commit()

    def _get_session_override():
        return session

    # Patch get_session used inside router
    monkeypatch.setattr("dashboard.backend.app.routers.universe.get_session", _get_session_override)

    result = asyncio.get_event_loop().run_until_complete(get_universe_bubble(limit=10))

    assert len(result) == 1
    item = result[0]
    assert isinstance(item, UniverseBubbleSchema)
    assert item.sold_live_qty == 2.0
    assert item.sold_dry_run_qty == 1.5
    assert item.sold_qty == 3.5

