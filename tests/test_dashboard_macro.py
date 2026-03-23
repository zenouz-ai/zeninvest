"""Tests for dashboard macro / World News router."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.backend.app.routers.macro import (
    get_latest_state,
    get_state_history,
    get_headlines,
    get_macro_summary,
)
from src.data.models import Base, MacroHeadline, MacroState

import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def _seed_state(Session, regime="NEUTRAL", age_hours=0):
    session = Session()
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    row = MacroState(
        timestamp=ts,
        regime=regime,
        confidence_score=0.65,
        source="scheduled_scan",
        top_signals_json=json.dumps([{"signal_type": "volatility", "signal_text": "VIX at 18.0", "source": "market_data"}]),
        action_plan_json=json.dumps({"portfolio_bias": "balanced", "risks": [], "opportunities": []}),
        sector_summary="- Tech: +0.5%",
        economic_highlights="- Fed holds rates",
    )
    session.add(row)
    session.commit()
    session.close()
    return row


def _seed_headlines(Session, count=5, age_days=0, category="fed"):
    session = Session()
    base_dt = datetime.now(timezone.utc) - timedelta(days=age_days)
    for i in range(count):
        session.add(MacroHeadline(
            headline=f"Test headline {i} {category}",
            source="Reuters",
            published_at=base_dt - timedelta(hours=i),
            url=f"https://example.com/{i}",
            category=category,
        ))
    session.commit()
    session.close()


class TestGetLatestState:
    def test_returns_none_when_empty(self):
        Session, _ = _make_session_factory()
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_latest_state())
        assert result is None

    def test_returns_latest_state(self):
        Session, _ = _make_session_factory()
        _seed_state(Session, regime="RISK_ON")
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_latest_state())
        assert result is not None
        assert result["regime"] == "RISK_ON"
        assert result["confidence_score"] == 0.65
        assert len(result["top_signals"]) == 1


class TestGetStateHistory:
    def test_returns_states_within_window(self):
        Session, _ = _make_session_factory()
        _seed_state(Session, regime="RISK_ON", age_hours=12)
        _seed_state(Session, regime="NEUTRAL", age_hours=0)
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_state_history(days=7))
        assert len(result) == 2

    def test_excludes_old_states(self):
        Session, _ = _make_session_factory()
        _seed_state(Session, regime="RISK_OFF", age_hours=24 * 10)
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_state_history(days=7))
        assert len(result) == 0


class TestGetHeadlines:
    def test_returns_headlines(self):
        Session, _ = _make_session_factory()
        _seed_headlines(Session, count=3, category="fed")
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_headlines(days=7, category="all", limit=200))
        assert len(result) == 3

    def test_filters_by_category(self):
        Session, _ = _make_session_factory()
        _seed_headlines(Session, count=3, category="fed")
        _seed_headlines(Session, count=2, category="trade")
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_headlines(days=7, category="trade", limit=200))
        assert len(result) == 2

    def test_excludes_old_headlines(self):
        Session, _ = _make_session_factory()
        _seed_headlines(Session, count=3, age_days=10, category="fed")
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_headlines(days=7, category="all", limit=200))
        assert len(result) == 0


class TestGetMacroSummary:
    def test_returns_summary_with_data(self):
        Session, _ = _make_session_factory()
        _seed_state(Session, regime="RISK_OFF")
        _seed_headlines(Session, count=5, category="fed")
        _seed_headlines(Session, count=3, category="trade")
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_macro_summary())
        assert result.regime == "RISK_OFF"
        assert result.headline_count_7d == 8
        assert result.category_counts["fed"] == 5
        assert result.category_counts["trade"] == 3
        assert result.top_signal == "VIX at 18.0"

    def test_returns_empty_summary_when_no_data(self):
        Session, _ = _make_session_factory()
        with patch("dashboard.backend.app.routers.macro.get_session", side_effect=lambda: Session()), \
             patch("dashboard.backend.app.routers.macro.settings") as mock_settings:
            mock_settings.dashboard_enabled = True
            result = _run(get_macro_summary())
        assert result.regime is None
        assert result.headline_count_7d == 0
