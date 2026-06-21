"""Tests for shadow learning alert collection and emission."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, DecisionShadowScore, LearningEvaluationRun
from src.learning.evaluation.alerts import collect_learning_alerts, emit_learning_alerts_if_needed


@pytest.fixture
def alerts_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _get_session():
        return session

    monkeypatch.setattr("src.learning.evaluation.alerts.get_session", _get_session)
    monkeypatch.setattr("src.learning.evaluation.outcome_join.get_session", _get_session)
    yield session
    session.close()


def _settings(**overrides):
    base = {
        "learning_alerts_enabled": True,
        "learning_alerts_shadow_disagreement_threshold": 0.5,
        "learning_alerts_min_shadow_scores": 2,
    }
    base.update(overrides)

    class FakeSettings:
        pass

    obj = FakeSettings()
    for key, value in base.items():
        setattr(obj, key, value)
    return obj


def test_collect_gate_regression_alert(alerts_session, monkeypatch):
    monkeypatch.setattr(
        "src.learning.evaluation.alerts.get_settings",
        lambda: _settings(),
    )
    alerts_session.add(
        LearningEvaluationRun(
            run_id="eval-1",
            dataset_version="v6",
            status="completed",
            n_rows=100,
            closed_trades=50,
            metrics_json=json.dumps({"artifact_run_id": "train-1"}),
            gates_json=json.dumps({"stop_the_line": ["gbm_big_winner_recall"]}),
            artifact_run_id="train-1",
        )
    )
    alerts_session.commit()

    monkeypatch.setattr(
        "src.learning.evaluation.alerts.shadow_summary",
        lambda days=30: {"span_days": 10, "total_scores": 0, "by_policy": {}},
    )
    monkeypatch.setattr(
        "src.learning.evaluation.alerts.check_promotion_gates",
        lambda **kwargs: type(
            "GateReport",
            (),
            {
                "stop_the_line": ["gbm_big_winner_recall"],
                "summary": "recall below threshold",
            },
        )(),
    )

    alerts = collect_learning_alerts()
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "gate_regression"


def test_collect_shadow_disagreement_spike(alerts_session, monkeypatch):
    monkeypatch.setattr(
        "src.learning.evaluation.alerts.get_settings",
        lambda: _settings(learning_alerts_min_shadow_scores=2),
    )
    now = datetime.now(timezone.utc)
    for idx in range(3):
        alerts_session.add(
            DecisionShadowScore(
                cycle_id=f"c{idx}",
                ticker="AAPL_US_EQ",
                decision_ts=now,
                champion_action="buy",
                policy_id="challenger_gbm",
                recommended_action="skip" if idx < 2 else "buy",
                scores_json="{}",
                artifact_run_ids_json="{}",
            )
        )
    alerts_session.commit()

    alerts = collect_learning_alerts()
    spike = [a for a in alerts if a["alert_type"] == "shadow_disagreement_spike"]
    assert len(spike) == 1
    assert spike[0]["policy_id"] == "challenger_gbm"
    assert spike[0]["disagreement_rate"] >= 0.5


def test_emit_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "src.learning.evaluation.alerts.get_settings",
        lambda: _settings(learning_alerts_enabled=False),
    )
    result = emit_learning_alerts_if_needed()
    assert result["status"] == "skipped"


def test_emit_sends_notifications(monkeypatch, alerts_session):
    monkeypatch.setattr(
        "src.learning.evaluation.alerts.get_settings",
        lambda: _settings(learning_alerts_min_shadow_scores=1),
    )
    now = datetime.now(timezone.utc)
    alerts_session.add(
        DecisionShadowScore(
            cycle_id="c1",
            ticker="AAPL_US_EQ",
            decision_ts=now,
            champion_action="buy",
            policy_id="challenger_gbm",
            recommended_action="skip",
            scores_json="{}",
            artifact_run_ids_json="{}",
        )
    )
    alerts_session.commit()

    fake_service = MagicMock()
    monkeypatch.setattr(
        "src.agents.notifications.NotificationService",
        lambda: fake_service,
    )

    result = emit_learning_alerts_if_needed()
    assert result["status"] == "ok"
    assert result["alerts_emitted"] >= 1
    fake_service.emit_learning_alert.assert_called()
