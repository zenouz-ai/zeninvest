"""Tests for shadow entry advisory summary."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.learning.evaluation.outcome_join import entry_advisory_summary


@pytest.fixture
def patch_learning_get_session(orchestrator_session_factory):
    with patch(
        "src.learning.evaluation.outcome_join.get_session",
        side_effect=orchestrator_session_factory,
    ):
        yield


def test_entry_advisory_empty_db(patch_learning_get_session) -> None:
    summary = entry_advisory_summary(days=30)
    assert summary["advisory_only"] is True
    assert summary["live_influence_enabled"] is False
    assert summary["influence_gate_closed_trades"] == 200
    assert summary["total_buy_scores"] == 0
