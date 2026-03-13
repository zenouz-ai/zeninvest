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

from src.data.models import Base, Instrument, StrategyDecision
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
    settings.effective_screening_cooldown_hours = None  # Use base when None
    settings.review_window_hours = [24, 48]
    settings.uninvestigated_target_pct = 0.5
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
        # Should contain stocks from the seed list (sector-balanced sample may vary)
        tickers = {c["ticker"] for c in candidates}
        assert all(t.endswith("_US_EQ") or t.endswith("_UK_EQ") for t in tickers), f"Expected seed-format tickers, got {tickers}"

    def test_all_in_cooldown_uses_least_recently_screened_rotation(self, db_session, fetcher):
        """When all instruments are in cooldown, fallback should order by last_screened_at ASC."""
        # Need pool >= 2*max_candidates (20) to avoid proactive seed; add 20 instruments all in cooldown
        recent_a = datetime.now(timezone.utc) - timedelta(hours=50)
        recent_b = datetime.now(timezone.utc) - timedelta(hours=30)
        recent_c = datetime.now(timezone.utc) - timedelta(hours=10)
        _make_instrument(db_session, "OLDEST_US_EQ", "Technology", 5e12, last_screened_at=recent_a)
        _make_instrument(db_session, "MIDDLE_US_EQ", "Technology", 4e12, last_screened_at=recent_b)
        _make_instrument(db_session, "NEWEST_US_EQ", "Technology", 3e12, last_screened_at=recent_c)
        for i in range(17):
            t = f"EXTRA{i}_US_EQ"
            _make_instrument(db_session, t, "Technology", 3e12 - i * 1e9, last_screened_at=recent_b)

        candidates = fetcher.get_screened_universe()
        tickers = [c["ticker"] for c in candidates]
        assert len(tickers) >= 1
        assert tickers[0] == "OLDEST_US_EQ", f"Expected OLDEST first (least recently screened), got {tickers}"

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


class TestReviewNewBucketing:
    """Tests for time-based review (24-48h) vs new (never or >48h) bucketing."""

    def _add_decision(self, session, ticker: str, hours_ago: float):
        """Add a StrategyDecision for ticker at given hours ago."""
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        session.add(StrategyDecision(
            cycle_id="test",
            ticker=ticker,
            action="HOLD",
            timestamp=ts,
        ))
        session.commit()

    def test_review_bucket_includes_24_to_48h_investigated(self, db_session, fetcher):
        """Tickers investigated 24-48h ago should be in review pool and eligible."""
        # Screened 80h ago so past 72h cooldown; AAPL investigated 36h ago (review window), MSFT 60h ago (new)
        now = datetime.now(timezone.utc)
        screened_80h = now - timedelta(hours=80)
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=screened_80h)
        _make_instrument(db_session, "MSFT_US_EQ", "Technology", 2.5e12, last_screened_at=screened_80h)
        self._add_decision(db_session, "AAPL_US_EQ", 36)  # investigated 36h ago = review (24-48h)
        self._add_decision(db_session, "MSFT_US_EQ", 60)  # 60h ago = new bucket

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers
        assert "MSFT_US_EQ" in tickers

    def test_new_bucket_includes_never_investigated(self, db_session, fetcher):
        """Tickers with no StrategyDecision should be in new pool."""
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12)
        _make_instrument(db_session, "MSFT_US_EQ", "Technology", 2.5e12)

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers
        assert "MSFT_US_EQ" in tickers

    def test_new_bucket_includes_over_48h_investigated(self, db_session, fetcher):
        """Tickers last investigated >48h ago should be in new pool."""
        # Screened 80h ago so past 72h cooldown; investigated 60h ago = new bucket
        now = datetime.now(timezone.utc)
        screened_80h = now - timedelta(hours=80)
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=screened_80h)
        self._add_decision(db_session, "AAPL_US_EQ", 60)

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers


class TestEffectiveCooldownAndProactiveSeed:
    """Tests for effective_screening_cooldown_hours (intraday) and proactive seed when pool small."""

    def test_effective_cooldown_4h_makes_5h_screened_eligible(self, db_session, fetcher):
        """With effective_screening_cooldown_hours=4, instrument screened 5h ago is past cooldown."""
        fetcher.settings.effective_screening_cooldown_hours = 4
        screened_5h = datetime.now(timezone.utc) - timedelta(hours=5)
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=screened_5h)

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" in tickers

    def test_effective_cooldown_4h_excludes_2h_screened(self, db_session, fetcher):
        """With effective_screening_cooldown_hours=4, instrument screened 2h ago is in cooldown."""
        fetcher.settings.effective_screening_cooldown_hours = 4
        screened_2h = datetime.now(timezone.utc) - timedelta(hours=2)
        _make_instrument(db_session, "AAPL_US_EQ", "Technology", 3e12, last_screened_at=screened_2h)
        _make_instrument(db_session, "MSFT_US_EQ", "Technology", 2.5e12)  # never screened

        candidates = fetcher.get_screened_universe()
        tickers = {c["ticker"] for c in candidates}
        assert "AAPL_US_EQ" not in tickers
        assert "MSFT_US_EQ" in tickers

    def test_proactive_seed_when_pool_below_threshold(self, db_session, fetcher):
        """When pool has < 2*max_candidates eligible, fallback should bootstrap with seed."""
        # Add only 5 instruments (below 2*10=20 threshold)
        for i, ticker in enumerate(["AAPL_US_EQ", "MSFT_US_EQ", "GOOGL_US_EQ", "AMZN_US_EQ", "NVDA_US_EQ"]):
            _make_instrument(
                db_session, ticker, "Technology",
                50_000_000_000 - i * 1e9,  # above small_cap_min
            )
        # Mark all 5 as recently screened so main path returns 0, triggering fallback
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        for inst in db_session.query(Instrument).all():
            inst.last_screened_at = recent
        db_session.commit()

        candidates = fetcher.get_screened_universe()
        # Proactive seed merges ~160; fallback returns up to max_candidates (10)
        assert len(candidates) >= 1, "Should get candidates after proactive seed bootstrap"
        assert len(candidates) <= 10, "Should cap at max_candidates"
