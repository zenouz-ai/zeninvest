"""Tests for market guidance generation and guided screening."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.guidance.service import GuidanceService
from src.agents.market_data.data_fetcher import DataFetcher
from src.data.models import Base, GuidanceSectorScore, GuidanceSnapshot, Instrument, MacroState


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def test_guidance_snapshot_persists_sector_scores() -> None:
    Session, _ = _make_session_factory()
    session = Session()
    ts = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(
        MacroState(
            timestamp=ts,
            regime="RISK_OFF",
            confidence_score=0.7,
            source="scheduled_scan",
            top_signals_json=json.dumps([{"signal_type": "volatility", "signal_text": "Risk-off breadth"}]),
            action_plan_json=json.dumps(
                {
                    "summary": "Tilt defensive.",
                    "sector_implications": [
                        {"sector": "Utilities", "bias": "favored", "rationale": "Defensive ballast"},
                        {"sector": "Technology", "bias": "avoid", "rationale": "Rate sensitivity"},
                    ],
                }
            ),
        )
    )
    session.add_all(
        [
            Instrument(ticker="XLU_US_EQ", name="Utilities ETF", sector="Utilities", market_cap=10_000_000_000),
            Instrument(ticker="XLK_US_EQ", name="Tech ETF", sector="Technology", market_cap=10_000_000_000),
            Instrument(ticker="XLF_US_EQ", name="Financial ETF", sector="Financial Services", market_cap=10_000_000_000),
        ]
    )
    session.commit()
    session.close()

    with patch("src.agents.guidance.service.get_session", side_effect=lambda: Session()):
        service = GuidanceService()
        payload = service.build_cycle_guidance(
            cycle_id="cycle-guidance-1",
            cycle_started_at=datetime.now(timezone.utc),
        )

    assert payload is not None
    assert payload["status"] == "active"
    sector_labels = {item["sector"]: item["label"] for item in payload["sector_scores"]}
    assert sector_labels["Utilities"] == "favored"
    assert sector_labels["Technology"] == "avoid"

    verify_session = Session()
    try:
        assert verify_session.query(GuidanceSnapshot).count() == 1
        assert verify_session.query(GuidanceSectorScore).count() >= 2
    finally:
        verify_session.close()


def test_guided_screening_prioritizes_favored_and_caps_avoid() -> None:
    fetcher = DataFetcher()
    instruments = [
        SimpleNamespace(ticker="AAA", sector="Technology"),
        SimpleNamespace(ticker="AAB", sector="Technology"),
        SimpleNamespace(ticker="AAC", sector="Technology"),
        SimpleNamespace(ticker="BBB", sector="Utilities"),
        SimpleNamespace(ticker="BBC", sector="Utilities"),
        SimpleNamespace(ticker="CCC", sector="Healthcare"),
    ]
    guidance = {
        "enabled": True,
        "favored_sectors": ["Utilities"],
        "avoid_sectors": ["Technology"],
    }

    selected = fetcher._sample_bucket_with_guidance(instruments, 4, 2, guidance)  # noqa: SLF001

    sectors = [item.sector for item in selected]
    assert sectors.count("Utilities") >= 2
    assert sectors.count("Technology") <= 1
