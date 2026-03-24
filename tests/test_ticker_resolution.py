"""Tests for ticker resolution utility (US-1.6)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from src.data.models import Base, Instrument
from src.utils.ticker_utils import resolve_ticker_to_t212


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

    # Seed some instruments
    session.add(Instrument(ticker="AAPL_US_EQ", name="Apple Inc"))
    session.add(Instrument(ticker="TSLA_US_EQ", name="Tesla Inc"))
    session.add(Instrument(ticker="MSFT_US_EQ", name="Microsoft Corporation"))
    session.add(Instrument(ticker="BP._UK_EQ", name="BP plc"))
    session.add(Instrument(ticker="DMYI_US_EQ", name="IonQ"))
    session.commit()

    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.utils.ticker_utils.get_session", return_value=db_session):
        yield


class TestResolveTickerToT212:

    def test_plain_symbol_resolves(self):
        """AAPL -> AAPL_US_EQ via _US_EQ suffix."""
        result = resolve_ticker_to_t212("AAPL")
        assert result == "AAPL_US_EQ"

    def test_exact_t212_format(self):
        """AAPL_US_EQ already in T212 format."""
        result = resolve_ticker_to_t212("AAPL_US_EQ")
        assert result == "AAPL_US_EQ"

    def test_case_insensitive(self):
        """aapl should resolve (uppercased before lookup)."""
        result = resolve_ticker_to_t212("aapl")
        assert result == "AAPL_US_EQ"

    def test_name_search_fallback(self):
        """'Apple' resolves via name search."""
        result = resolve_ticker_to_t212("APPLE")
        assert result == "AAPL_US_EQ"

    def test_name_search_handles_internal_t212_symbol(self):
        """IonQ resolves to the currently-listed Trading 212 instrument id."""
        result = resolve_ticker_to_t212("IONQ")
        assert result == "DMYI_US_EQ"

    def test_unknown_returns_none(self):
        """Unknown ticker returns None."""
        result = resolve_ticker_to_t212("ZZZZZ")
        assert result is None

    def test_empty_returns_none(self):
        assert resolve_ticker_to_t212("") is None
        assert resolve_ticker_to_t212("  ") is None
