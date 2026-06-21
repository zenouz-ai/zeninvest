"""Shadow learning alert checks (gate regression + disagreement spikes)."""

from __future__ import annotations

import json
from typing import Any

from src.data.database import get_session
from src.data.models import LearningEvaluationRun
from src.learning.evaluation.gates import check_promotion_gates
from src.learning.evaluation.outcome_join import shadow_summary
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.evaluation.alerts")


def collect_learning_alerts(*, shadow_days: int = 30) -> list[dict[str, Any]]:
    """Return alert payloads for gate regression and shadow disagreement spikes."""
    settings = get_settings()
    alerts: list[dict[str, Any]] = []
    session = get_session()
    try:
        row = (
            session.query(LearningEvaluationRun)
            .order_by(LearningEvaluationRun.created_at.desc())
            .first()
        )
        if row is not None:
            metrics = json.loads(row.metrics_json) if row.metrics_json else {}
            train_metrics: dict[str, Any] = {}
            artifact_id = row.artifact_run_id or metrics.get("artifact_run_id")
            if artifact_id:
                from src.learning.evaluation.gbm_inference import project_root

                metrics_path = (
                    project_root() / "data" / "learning" / "reports" / artifact_id / "metrics.json"
                )
                if metrics_path.exists():
                    train_metrics = json.loads(metrics_path.read_text())

            shadow = shadow_summary(days=shadow_days)
            gates = check_promotion_gates(
                evaluation_metrics=metrics,
                train_metrics=train_metrics,
                closed_trades=int(row.closed_trades or 0),
                shadow_days=int(shadow.get("span_days") or 0),
                shadow_rows=int(shadow.get("total_scores") or 0),
            )
            if gates.stop_the_line:
                alerts.append(
                    {
                        "alert_type": "gate_regression",
                        "severity": "warning",
                        "evaluation_run_id": row.run_id,
                        "stop_the_line": gates.stop_the_line,
                        "summary": gates.summary,
                    }
                )
    finally:
        session.close()

    shadow = shadow_summary(days=shadow_days)
    threshold = settings.learning_alerts_shadow_disagreement_threshold
    min_scores = settings.learning_alerts_min_shadow_scores
    for policy_id, bucket in (shadow.get("by_policy") or {}).items():
        n = int(bucket.get("n") or 0)
        if n < min_scores:
            continue
        disagreements = int(bucket.get("disagreements") or 0)
        rate = disagreements / n if n else 0.0
        if rate >= threshold:
            alerts.append(
                {
                    "alert_type": "shadow_disagreement_spike",
                    "severity": "warning",
                    "policy_id": policy_id,
                    "disagreement_rate": round(rate, 4),
                    "disagreements": disagreements,
                    "total_scores": n,
                    "threshold": threshold,
                    "span_days": shadow.get("span_days"),
                }
            )

    return alerts


def emit_learning_alerts_if_needed(*, shadow_days: int = 30) -> dict[str, Any]:
    """Evaluate learning alerts and emit notifications when enabled."""
    settings = get_settings()
    if not settings.learning_alerts_enabled:
        return {"status": "skipped", "reason": "alerts_disabled"}

    alerts = collect_learning_alerts(shadow_days=shadow_days)
    if not alerts:
        return {"status": "ok", "alerts_emitted": 0}

    from src.agents.notifications import NotificationService

    notifications = NotificationService()
    emitted = 0
    for alert in alerts:
        severity = str(alert.get("severity", "warning"))
        notifications.emit_learning_alert(payload=alert, severity=severity)  # type: ignore[arg-type]
        emitted += 1

    logger.info("Emitted %s learning alert(s)", emitted)
    return {"status": "ok", "alerts_emitted": emitted, "alerts": alerts}
