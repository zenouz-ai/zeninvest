"""Tests for learning memory vector store (US-6.2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.learning.memory import vector_store


def test_cosine_identical_vectors():
    vec = [1.0, 0.0, 0.0]
    assert vector_store._cosine(vec, vec) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert vector_store._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_save_and_load_index(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    rows = [
        {
            "doc_id": "d1",
            "cycle_id": "c1",
            "ticker": "AAPL_US_EQ",
            "decision_ts": "2026-01-01T00:00:00+00:00",
            "metadata": {},
            "embedding": [1.0, 0.0],
        }
    ]
    path = vector_store.save_index(rows)
    assert Path(path).exists()
    loaded = vector_store.load_index()
    assert len(loaded) == 1
    assert loaded[0]["doc_id"] == "d1"


def test_search_similar_empty_index(monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", "/tmp/nonexistent_learning_root_xyz")
    monkeypatch.setattr(vector_store, "embed_texts", lambda texts: [[1.0, 0.0]])
    assert vector_store.search_similar("query", k=3) == []


def test_build_index_from_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    jsonl = tmp_path / "exports" / "v6" / "memory_bundle.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(
        json.dumps(
            {
                "doc_id": "d1",
                "cycle_id": "c1",
                "ticker": "AAPL_US_EQ",
                "decision_ts": "2026-01-01T00:00:00+00:00",
                "body": "momentum thesis",
                "metadata": {"label_3class": "big_winner"},
            }
        )
        + "\n"
    )
    monkeypatch.setattr(vector_store, "embed_texts", lambda texts: [[1.0, 0.0]])
    with patch("src.utils.cost_tracker.check_embedding_budget", return_value=True):
        result = vector_store.build_index_from_jsonl(jsonl_path=jsonl)
    assert result["indexed"] == 1
    loaded = vector_store.load_index()
    assert len(loaded) == 1


def test_search_similar_filters_ticker_and_as_of(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    rows = [
        {
            "doc_id": "d1",
            "cycle_id": "c1",
            "ticker": "AAPL_US_EQ",
            "decision_ts": "2026-01-01T00:00:00+00:00",
            "metadata": {},
            "embedding": [1.0, 0.0],
        },
        {
            "doc_id": "d2",
            "cycle_id": "c2",
            "ticker": "MSFT_US_EQ",
            "decision_ts": "2026-02-01T00:00:00+00:00",
            "metadata": {},
            "embedding": [0.0, 1.0],
        },
    ]
    vector_store.save_index(rows)
    monkeypatch.setattr(vector_store, "embed_texts", lambda texts: [[1.0, 0.0]])
    with patch("src.utils.cost_tracker.check_embedding_budget", return_value=True):
        by_ticker = vector_store.search_similar("query", ticker="AAPL_US_EQ", k=5)
        assert len(by_ticker) == 1
        assert by_ticker[0]["ticker"] == "AAPL_US_EQ"

        before = vector_store.search_similar("query", as_of_ts="2026-01-15T00:00:00+00:00", k=5)
        assert len(before) == 1
        assert before[0]["doc_id"] == "d1"


def test_build_index_skips_when_budget_exhausted(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    jsonl = tmp_path / "exports" / "v6" / "memory_bundle.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(json.dumps({"doc_id": "d1", "body": "text"}) + "\n")
    with patch("src.utils.cost_tracker.check_embedding_budget", return_value=False):
        result = vector_store.build_index_from_jsonl(jsonl_path=jsonl)
    assert result.get("skipped") == "embedding_budget"
    assert result["indexed"] == 0
