import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.backend.app.routers.universe import get_instrument, get_universe_bubble
from dashboard.backend.app.schemas import UniverseBubbleSchema
from src.data.models import Base, Instrument, Order, ResearchLog, StrategyDecision


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


def test_universe_bubble_separates_latest_cycle_research_from_total(monkeypatch):
    session = _make_session()

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

    session.add_all([
        StrategyDecision(
            cycle_id="cycle-old",
            ticker="TEST_US_EQ",
            action="BUY",
            conviction=70,
            timestamp=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
        ),
        StrategyDecision(
            cycle_id="cycle-new",
            ticker="TEST_US_EQ",
            action="HOLD",
            conviction=65,
            timestamp=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        ),
        ResearchLog(
            cycle_id="cycle-old",
            member="strategy",
            ticker="TEST_US_EQ",
            tool_name="news_search",
            query="older research",
            num_results=3,
            results_json='[{"url":"https://example.com/old"}]',
            provider="brave",
            cache_hit=False,
        ),
        ResearchLog(
            cycle_id="cycle-old",
            member="strategy",
            ticker="TEST_US_EQ",
            tool_name="web_search",
            query="older research 2",
            num_results=2,
            results_json='[{"url":"https://example.com/old-2"}]',
            provider="brave",
            cache_hit=False,
        ),
        ResearchLog(
            cycle_id="cycle-new",
            member="strategy",
            ticker="TEST_US_EQ",
            tool_name="news_search",
            query="latest research",
            num_results=1,
            results_json='[{"url":"https://example.com/new"}]',
            provider="brave",
            cache_hit=False,
        ),
    ])
    session.commit()

    def _get_session_override():
        return session

    monkeypatch.setattr("dashboard.backend.app.routers.universe.get_session", _get_session_override)

    result = asyncio.get_event_loop().run_until_complete(get_universe_bubble(limit=10))

    assert len(result) == 1
    item = result[0]
    assert item.research_calls == 3
    assert item.research_calls_latest_cycle == 1


def test_get_instrument_scopes_research_to_latest_cycle_and_explains_hold_short_circuit(monkeypatch):
    session = _make_session()

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

    session.add_all([
        StrategyDecision(
            cycle_id="cycle-old",
            ticker="TEST_US_EQ",
            action="BUY",
            conviction=80,
            reasoning="Old actionable thesis",
            timestamp=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
        ),
        StrategyDecision(
            cycle_id="cycle-new",
            ticker="TEST_US_EQ",
            action="HOLD",
            conviction=65,
            reasoning="Latest cycle decided to hold",
            timestamp=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        ),
        ResearchLog(
            cycle_id="cycle-old",
            member="strategy",
            ticker="TEST_US_EQ",
            tool_name="news_search",
            query="older research",
            num_results=2,
            results_json='[{"url":"https://example.com/old"}]',
            provider="brave",
            cache_hit=False,
        ),
        ResearchLog(
            cycle_id="cycle-new",
            member="strategy",
            ticker="TEST_US_EQ",
            tool_name="news_search",
            query="latest research",
            num_results=1,
            results_json='[{"url":"https://example.com/new"}]',
            provider="brave",
            cache_hit=False,
        ),
    ])
    session.commit()

    class _Settings:
        dashboard_enabled = True

    def _get_session_override():
        return session

    monkeypatch.setattr("dashboard.backend.app.routers.universe.get_session", _get_session_override)
    monkeypatch.setattr("dashboard.backend.app.routers.universe.settings", _Settings())

    detail = asyncio.get_event_loop().run_until_complete(get_instrument("TEST_US_EQ"))

    assert detail.last_decision is not None
    assert detail.last_decision["cycle_id"] == "cycle-new"
    assert detail.last_decision["latest_cycle_research_calls"] == 1
    assert detail.last_decision["total_research_calls"] == 2
    assert len(detail.last_decision["research"]) == 1
    assert detail.last_decision["research"][0]["query"] == "latest research"
    assert "latest strategy cycle only" in detail.last_decision["scope_note"]
    assert "Latest decision is HOLD" in detail.last_decision["pipeline_note"]
