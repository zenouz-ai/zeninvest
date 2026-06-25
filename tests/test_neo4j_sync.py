"""Tests for Neo4j memory sync (US-6.4)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.learning.memory import neo4j_sync


def test_query_similar_sector_regime_without_password():
    with patch.object(neo4j_sync, "get_settings") as mock_settings:
        mock_settings.return_value.learning_neo4j_password = ""
        assert neo4j_sync.query_similar_sector_regime("Tech", "RISK_ON") == []


def test_sync_neo4j_disabled():
    with patch.object(neo4j_sync, "get_settings") as mock_settings:
        mock_settings.return_value.learning_neo4j_enabled = False
        with pytest.raises(RuntimeError, match="neo4j_enabled=false"):
            neo4j_sync.sync_neo4j(jsonl_path="/nonexistent")


def test_sync_neo4j_requires_password(monkeypatch):
    with patch.object(neo4j_sync, "get_settings") as mock_settings:
        mock_settings.return_value.learning_neo4j_enabled = True
        mock_settings.return_value.learning_neo4j_password = ""
        with pytest.raises(RuntimeError, match="NEO4J_PASSWORD"):
            neo4j_sync.sync_neo4j(jsonl_path="/nonexistent")


def test_sync_neo4j_upserts_from_jsonl(tmp_path, monkeypatch):
    jsonl = tmp_path / "bundle.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "doc_id": "d1",
                "cycle_id": "c1",
                "ticker": "AAPL_US_EQ",
                "decision_ts": "2026-01-01T00:00:00+00:00",
                "body": "thesis",
                "metadata": {
                    "action": "BUY",
                    "conviction": 0.8,
                    "label_3class": "big_winner",
                    "realized_pnl_pct": 12.0,
                    "macro_regime": "RISK_ON",
                    "sector": "Technology",
                },
            }
        )
        + "\n"
    )

    import sys

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    fake_neo4j = MagicMock()
    fake_neo4j.GraphDatabase.driver.return_value = mock_driver

    with (
        patch.object(neo4j_sync, "get_settings") as mock_settings,
        patch.dict(sys.modules, {"neo4j": fake_neo4j}),
    ):
        mock_settings.return_value.learning_neo4j_enabled = True
        mock_settings.return_value.learning_neo4j_password = "secret"
        mock_settings.return_value.learning_neo4j_uri = "bolt://localhost:7687"
        mock_settings.return_value.learning_neo4j_user = "neo4j"

        result = neo4j_sync.sync_neo4j(jsonl_path=jsonl)

    assert result["nodes_upserted"] == 1
    assert mock_session.run.call_count >= 2
    first_call = mock_session.run.call_args_list[0]
    assert "MERGE (d:Decision" in first_call[0][0]
    assert first_call[1]["doc_id"] == "d1"
