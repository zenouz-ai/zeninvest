"""Tests for rejection funnel integration in offline evaluation (US-6.7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.dataset.rejection_analysis import (
    compute_funnel_metrics,
    load_latest_rejection_analysis,
)
from src.learning.evaluation.report import _render_html


def test_compute_funnel_metrics_basic():
    import pandas as pd

    from src.learning.dataset.rejection_analysis import LOSER, WINNER

    rejected = pd.DataFrame(
        {
            "cf_label": [LOSER, WINNER, LOSER],
            "forward_ret_pct": [-5.0, 10.0, -3.0],
        }
    )
    accepted = pd.DataFrame(
        {
            "cf_label": [WINNER, LOSER],
            "forward_ret_pct": [8.0, -2.0],
        }
    )
    metrics = compute_funnel_metrics(rejected, accepted)
    assert metrics["rejected_count"] == 3
    assert metrics["accepted_count"] == 2
    assert metrics["forward_precision_at_veto"] == pytest.approx(2 / 3, abs=1e-3)
    assert metrics["missed_winner_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_load_latest_rejection_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    reports = tmp_path / "reports"
    reports.mkdir()
    payload = {"rejected_total": 10, "funnel_metrics": {"forward_precision_at_veto": 0.5}}
    (reports / "rejected_analysis_20260601.json").write_text(json.dumps(payload))
    loaded = load_latest_rejection_analysis()
    assert loaded is not None
    assert loaded["rejected_total"] == 10


def test_evaluation_html_includes_rejection_funnel():
    html = _render_html(
        {
            "run_id": "eval-test",
            "n_rows": 1,
            "closed_trades": 0,
            "dataset_version": "v6",
            "policies": {},
            "gates": {"summary": "test", "tiers": []},
            "disagreements": [],
            "rejection_funnel": {
                "rejected_total": 100,
                "coverage_pct": 0.9,
                "good_miss_rate": 0.35,
                "false_reject_rate": 0.2,
                "selection_gap_pct": -1.5,
                "generated_at": "2026-06-21T00:00:00+00:00",
                "funnel_metrics": {
                    "forward_precision_at_veto": 0.35,
                    "missed_winner_rate": 0.2,
                },
            },
        }
    )
    assert "Full-funnel rejection quality" in html
    assert "35.0%" in html
