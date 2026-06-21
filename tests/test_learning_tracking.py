"""Tests for optional MLflow mirror logging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.learning.tracking import mirror_train_run_to_mlflow


def test_mirror_skips_when_disabled(monkeypatch):
    class FakeSettings:
        learning_mlflow_enabled = False
        learning_mlflow_uri = "file:./data/learning/mlflow"

    monkeypatch.setattr("src.learning.tracking.get_settings", lambda: FakeSettings())
    result = mirror_train_run_to_mlflow(
        run_id="run-1",
        dataset_version="v6",
        seed=42,
        metrics={"metadata": {}, "gbm": {}},
        booster_dir=Path("/tmp/models"),
        label_config={"embargo_days": 5},
        git_commit="abc123",
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "mlflow_disabled"


def test_mirror_logs_when_enabled(monkeypatch, tmp_path):
    class FakeSettings:
        learning_mlflow_enabled = True
        learning_mlflow_uri = f"file:{tmp_path / 'mlflow'}"

    monkeypatch.setattr("src.learning.tracking.get_settings", lambda: FakeSettings())

    booster_dir = tmp_path / "models" / "run-1"
    gbm_dir = booster_dir / "gbm"
    gbm_dir.mkdir(parents=True)
    (gbm_dir / "fold_0.txt").write_text("fake")

    fake_mlflow = MagicMock()
    fake_run = MagicMock()
    fake_mlflow.start_run.return_value.__enter__.return_value = fake_run
    monkeypatch.setitem(__import__("sys").modules, "mlflow", fake_mlflow)

    result = mirror_train_run_to_mlflow(
        run_id="run-1",
        dataset_version="v6",
        seed=7,
        metrics={
            "metadata": {"dataset_checksum": "chk"},
            "gbm": {"aggregate_metrics": {"accuracy": 0.5}},
            "stall": {"metrics": {"auc": 0.55}},
            "calibrator": {"metrics": {"brier": 0.2}},
        },
        booster_dir=booster_dir,
        label_config={"embargo_days": 5},
        git_commit="abc123",
    )

    assert result["status"] == "logged"
    fake_mlflow.set_tracking_uri.assert_called_once()
    fake_mlflow.log_param.assert_any_call("dataset_version", "v6")
    fake_mlflow.log_metric.assert_any_call("gbm_accuracy", 0.5)
