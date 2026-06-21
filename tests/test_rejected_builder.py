"""Tests for rejected parquet builder (US-6.7)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, OpportunityScoreSnapshot
from src.learning.dataset.rejected_builder import build_rejected_parquet


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path / "learning"))
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


def test_build_rejected_parquet_empty(session):
    result = build_rejected_parquet(session)
    assert result["rows"] == 0
    assert result["parquet_path"] is None


def test_build_rejected_parquet_writes_file(session, tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path / "learning"))
    ts = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    session.add(
        OpportunityScoreSnapshot(
            timestamp=ts,
            cycle_id="c1",
            ticker="LOSE_US_EQ",
            action="HOLD",
            stage="risk_reject",
            is_tradable=False,
        )
    )
    session.commit()

    from src.learning.dataset import rejection_analysis

    monkeypatch.setattr(
        rejection_analysis,
        "label_rows",
        lambda *args, **kwargs: __import__("pandas").DataFrame(
            {
                "cycle_id": ["c1"],
                "ticker": ["LOSE_US_EQ"],
                "timestamp": [ts],
                "stage": ["risk_reject"],
                "forward_ret_pct": [-10.0],
                "cf_label": ["big_loser"],
            }
        ),
    )
    monkeypatch.setattr(
        rejection_analysis,
        "analyze_rejections",
        lambda *args, **kwargs: rejection_analysis.RejectionAnalysis(
            generated_at=ts.isoformat(),
            horizon_days=30,
            rejected_total=1,
            rejected_resolved=1,
            accepted_total=0,
            accepted_resolved=0,
            coverage_pct=1.0,
            good_miss_rate=1.0,
            false_reject_rate=0.0,
            stall_rate=0.0,
            rejected_mean_forward_ret_pct=-10.0,
            accepted_mean_forward_ret_pct=None,
            selection_gap_pct=None,
        ),
    )

    result = build_rejected_parquet(session)
    assert result["rows"] == 1
    assert Path(result["parquet_path"]).exists()
    assert Path(result["analysis_artifact"]).exists()
