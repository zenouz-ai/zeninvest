"""Tests for batch enrichment query and candidate selection."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.market_data.data_fetcher import DataFetcher
from src.data.models import Base, Instrument


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.agents.market_data.data_fetcher.get_session", return_value=db_session):
        yield


@pytest.fixture
def fetcher():
    df = DataFetcher.__new__(DataFetcher)
    settings = MagicMock()
    settings.batch_enrichment_per_run = 10
    df.settings = settings
    df._finnhub = MagicMock()
    df._alpha_vantage = MagicMock()
    df.last_screening_metadata = {}
    return df


def _add_instrument(session, ticker: str, *, sector=None, market_cap=None):
    session.add(
        Instrument(
            ticker=ticker,
            name=ticker,
            sector=sector,
            market_cap=market_cap,
            data_available=True,
        )
    )
    session.commit()


def test_count_enrichment_backlog_and_candidate_query(fetcher, db_session):
    """Batch enrichment filter must execute without SQLAlchemy tuple errors."""
    _add_instrument(db_session, "GOOD_US_EQ", sector="Technology", market_cap=1_000_000_000_000)
    _add_instrument(db_session, "MISSING_US_EQ", sector="Unknown", market_cap=0)
    _add_instrument(db_session, "EMPTY_US_EQ", sector=None, market_cap=None)

    assert fetcher.count_enrichment_backlog() == 2

    with patch(
        "src.agents.market_data.data_fetcher.get_fundamentals",
        return_value={"sector": "Healthcare", "market_cap": 500_000_000_000},
    ):
        enriched = fetcher.enrich_instruments_batch(max_per_run=5)

    assert enriched == 2
    missing = db_session.query(Instrument).filter_by(ticker="MISSING_US_EQ").one()
    assert missing.sector == "Healthcare"
    assert missing.market_cap == 500_000_000_000


def test_enrichment_prioritizes_us_candidates(fetcher, db_session):
    """US backlog should be processed before other markets when both need enrichment."""
    _add_instrument(db_session, "AAA_US_EQ", sector="Unknown", market_cap=0)
    _add_instrument(db_session, "BBB_UK_EQ", sector="Unknown", market_cap=0)

    seen: list[str] = []

    def fake_fundamentals(symbol: str):
        seen.append(symbol)
        return {"sector": "Financials", "market_cap": 1_000_000_000}

    with patch("src.agents.market_data.data_fetcher.get_fundamentals", side_effect=fake_fundamentals):
        fetcher.enrich_instruments_batch(max_per_run=1)

    assert seen == ["AAA"]
