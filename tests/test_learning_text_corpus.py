"""Tests for v2 text corpus sidecar and memory JSONL export."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.data.models import (
    MacroHeadline,
    StrategyDecision,
)
from src.learning.dataset.text_corpus import TextCorpusBuilder
from src.learning.spec import get_text_corpus_spec


@pytest.fixture
def seeded_text_db(orchestrator_db_session):
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    orchestrator_db_session.add(
        StrategyDecision(
            cycle_id="cycle_1",
            ticker="AAPL_US_EQ",
            action="BUY",
            conviction=75,
            primary_strategy="momentum",
            reasoning="Strong momentum thesis for Apple.",
            timestamp=ts,
        )
    )
    orchestrator_db_session.add(
        MacroHeadline(
            headline="Fed holds rates steady",
            source="Reuters",
            published_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            category="rates",
        )
    )
    orchestrator_db_session.add(
        MacroHeadline(
            headline="Future headline",
            source="Reuters",
            published_at=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
            category="rates",
        )
    )
    orchestrator_db_session.commit()
    return orchestrator_db_session


def test_text_corpus_excludes_future_headlines(seeded_text_db, tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    labels = pd.DataFrame(
        [
            {
                "cycle_id": "cycle_1",
                "ticker": "AAPL_US_EQ",
                "decision_ts": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
                "label_3class": "neutral",
                "realized_pnl_pct": None,
            }
        ]
    )
    builder = TextCorpusBuilder(seeded_text_db, project_root=tmp_path)
    df, paths = builder.build(
        [
            {
                "cycle_id": "cycle_1",
                "ticker": "AAPL_US_EQ",
                "timestamp": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
                "action": "BUY",
            }
        ],
        labels_df=labels,
        write=True,
    )
    assert len(df) == 1
    headlines = df.iloc[0]["macro_headlines"]
    assert len(headlines) == 1
    assert headlines[0]["headline"] == "Fed holds rates steady"
    assert "memory_bundle" in paths
    spec = get_text_corpus_spec()
    jsonl = tmp_path / spec.memory_bundle_path()
    assert jsonl.exists()


def test_graphiti_episode_export(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    spec = get_text_corpus_spec()
    bundle = tmp_path / spec.memory_bundle_path()
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(
        '{"doc_id":"abc","cycle_id":"c1","ticker":"AAPL_US_EQ",'
        '"decision_ts":"2026-05-01T12:00:00+00:00","metadata":{"macro_regime":"RISK_ON"},'
        '"body":"test thesis"}\n'
    )
    from src.learning.memory.graphiti_sync import sync_graphiti_episodes

    result = sync_graphiti_episodes(bundle)
    assert result["episodes"] == 1
    assert (tmp_path / "data" / "learning" / "graphiti" / spec.version / "episodes.json").exists()
