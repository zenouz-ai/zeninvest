"""Tests for research influence attribution helpers."""

from __future__ import annotations

import pandas as pd

from src.learning.evaluation.research_attribution import (
    _reasoning_cites_query,
    _research_bucket,
    compute_research_stratified,
)


def test_research_bucket_labels():
    assert _research_bucket(0) == "0"
    assert _research_bucket(2) == "1-2"
    assert _research_bucket(4) == "3-5"
    assert _research_bucket(8) == "6+"


def test_reasoning_cites_query_token_overlap():
    assert _reasoning_cites_query(
        "Recent earnings beat supports momentum thesis for regional banks",
        "regional bank earnings beat",
    )


def test_compute_research_stratified_by_intensity():
    df = pd.DataFrame(
        {
            "research_calls_total": [0, 1, 3, 0],
            "label_3class": ["big_winner", "big_loser", "stall", "neutral"],
            "actually_traded": [True, True, True, False],
            "trade_pnl_gbp": [10.0, -5.0, 1.0, None],
        }
    )
    result = compute_research_stratified(df)
    buckets = {row["bucket"]: row for row in result["by_intensity"]}
    assert "0" in buckets
    assert buckets["0"]["n"] == 2
