"""Tests for the screening cooldown mechanism."""

import sys
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

# Stub all heavy third-party and internal modules that data_fetcher imports
# so we can test without the full dependency tree.
_stubs = [
    "yfinance", "pandas", "httpx", "finnhub",
    "src.agents.market_data.alpha_vantage_client",
    "src.agents.market_data.finnhub_client",
    "src.agents.market_data.fundamentals",
    "src.agents.market_data.indicators",
    "src.utils.config",
    "src.utils.logger",
]
for mod in _stubs:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, Instrument
from src.agents.market_data.data_fetcher import DataFetcher


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
    """Patch get_session to use the test database."""
    with patch("src.agents.market_data.data_fetcher.get_session", return_value=db_session):
        yield


@pytest.fixture
def mock_settings():
    """Return a mock settings object with universe config."""
    settings = MagicMock()
    settings.max_candidates = 10
    settings.candidates_per_sector = 2
    settings.large_cap_pct = 0.40
    settings.mid_cap_pct = 0.35
    settings.small_cap_pct = 0.25
    settings.large_cap_min = 10_000_000_000
    settings.mid_cap_min = 2_000_000_000
    settings.small_cap_min = 300_000_000
    settings.screening_cooldown_hours = 72
    return settings


@pytest.fixture
def fetcher(mock_settings):
    """Create a DataFetcher with mocked settings."""
    df = DataFetcher.__new__(DataFetcher)
    df.settings = mock_settings
    return df


def _make_instrument(session, ticker, sector, market_cap, last_screened_at=None):
    """Helper to insert an instrument."""
    inst = Instrument(
        ticker=ticker,
        name=ticker,
        sector=sector,
        market_cap=market_cap,
        last_screened_at=last_screened_at,
    )
    session.add(inst)
    session.commit()
    return inst


class TestScreeningCooldown:
    def test_never_screened_instruments_are_included(self, db_session, fetcher):
        """Instruments with no last_screened_at should be eligible."""
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12)
        _make_instrument(db_session, "MSFT_US_EQ", "Technology", 2.5e12)

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers
        assert "MSFT_US_EQ" in tickers

    def test_recently_screened_instruments_are_excluded(self, db_session, fetcher):
        """Instruments screened within cooldown window should be excluded."""
        recent = datetime.now(timezone.utc) - timedelta(hours=10)  # 10h ago, within 72h
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=recent)
        _make_instrument(db_session, "GOOG_US_EQ", "Technology", 2e12)  # never screened

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" not in tickers
        assert "GOOG_US_EQ" in tickers

    def test_cooldown_expired_instruments_are_included(self, db_session, fetcher):
        """Instruments screened beyond the cooldown window should be eligible again."""
        old = datetime.now(timezone.utc) - timedelta(hours=100)  # 100h ago, past 72h
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=old)

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers

    def test_mark_instruments_screened_sets_timestamp(self, db_session, fetcher):
        """mark_instruments_screened should set last_screened_at."""
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12)
        _make_instrument(db_session, "MSFT_US_EQ", "Technology", 2.5e12)

        fetcher.mark_instruments_screened(["AAPL_US_EQ", "MSFT_US_EQ"])

        inst = db_session.query(Instrument).filter_by(ticker="AAPL_US_EQ").first()
        assert inst.last_screened_at is not None
        # Should be very recent
        delta = datetime.now(timezone.utc) - inst.last_screened_at.replace(tzinfo=timezone.utc)
        assert delta.total_seconds() < 5

    def test_mark_then_screen_excludes(self, db_session, fetcher):
        """After marking instruments as screened, they should not appear in the next screen."""
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12)
        _make_instrument(db_session, "GOOG_US_EQ", "Technology", 2e12)

        # Mark AAPL as screened
        fetcher.mark_instruments_screened(["AAPL_US_EQ"])

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" not in tickers
        assert "GOOG_US_EQ" in tickers

    def test_empty_tickers_no_error(self, fetcher):
        """mark_instruments_screened with empty list should be a no-op."""
        fetcher.mark_instruments_screened([])  # Should not raise


class TestDataAvailableFiltering:
    def test_unavailable_instruments_excluded_from_screen(self, db_session, fetcher):
        """Instruments with data_available=False should be excluded."""
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12)
        _make_instrument(db_session, "BAD_US_EQ", "Technology", 2e12)
        # Mark BAD as unavailable
        bad = db_session.query(Instrument).filter_by(ticker="BAD_US_EQ").first()
        bad.data_available = False
        db_session.commit()

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers
        assert "BAD_US_EQ" not in tickers

    def test_mark_instrument_unavailable(self, db_session, fetcher):
        """mark_instrument_unavailable should set data_available=False."""
        _make_instrument(db_session, "DELIST_US_EQ", "Technology", 1e12)
        fetcher.mark_instrument_unavailable("DELIST_US_EQ")

        inst = db_session.query(Instrument).filter_by(ticker="DELIST_US_EQ").first()
        assert inst.data_available is False

    def test_fallback_uses_seed_universe(self, db_session, fetcher):
        """When no enriched instruments exist, fallback should seed from curated list."""
        # No instruments in DB at all — fallback should populate from seeds
        candidates = fetcher.get_screened_universe()
        assert len(candidates) > 0
        # Should contain well-known stocks from the seed list
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers or "MSFT_US_EQ" in tickers

    def test_fallback_excludes_unavailable_seeds(self, db_session, fetcher):
        """Seed instruments marked unavailable should not appear in fallback."""
        # Pre-insert an instrument that's flagged unavailable
        db_session.add(Instrument(
            ticker="AAPL_US_EQ", name="Apple", sector=None,
            market_cap=None, data_available=False,
        ))
        db_session.commit()

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        # AAPL should not appear because it's flagged unavailable
        assert "AAPL_US_EQ" not in tickers
