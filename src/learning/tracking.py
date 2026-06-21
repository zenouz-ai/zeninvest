"""Optional MLflow mirror logging for learning train runs (feature-flagged)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.tracking")


def mirror_train_run_to_mlflow(
    *,
    run_id: str,
    dataset_version: str,
    seed: int,
    metrics: dict[str, Any],
    booster_dir: Path,
    label_config: dict[str, Any],
    git_commit: str | None,
) -> dict[str, Any]:
    """Mirror a completed train run to MLflow when enabled.

    SQLite + on-disk artifacts remain the source of truth; MLflow is a
    secondary index for experiment comparison when adoption triggers fire.
    """
    settings = get_settings()
    if not settings.learning_mlflow_enabled:
        return {"status": "skipped", "reason": "mlflow_disabled"}

    try:
        import mlflow
    except ImportError:
        logger.warning("learning.mlflow_enabled=true but mlflow is not installed")
        return {"status": "skipped", "reason": "mlflow_not_installed"}

    uri = settings.learning_mlflow_uri
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("zeninvest-learning")

    metadata = metrics.get("metadata") or {}
    gbm = metrics.get("gbm") or {}
    stall = metrics.get("stall") or {}
    calibrator = metrics.get("calibrator") or {}

    with mlflow.start_run(run_name=run_id):
        mlflow.log_param("dataset_version", dataset_version)
        mlflow.log_param("seed", seed)
        if git_commit:
            mlflow.log_param("git_commit", git_commit)
        if metadata.get("dataset_checksum"):
            mlflow.log_param("dataset_checksum", metadata["dataset_checksum"])
        for key, value in label_config.items():
            mlflow.log_param(f"label_{key}", value)

        aggregate = gbm.get("aggregate_metrics") or {}
        for key, value in aggregate.items():
            if isinstance(value, (int, float)):
                mlflow.log_metric(f"gbm_{key}", float(value))

        stall_metrics = stall.get("metrics") or {}
        for key, value in stall_metrics.items():
            if isinstance(value, (int, float)):
                mlflow.log_metric(f"stall_{key}", float(value))

        cal_metrics = calibrator.get("metrics") or {}
        for key, value in cal_metrics.items():
            if isinstance(value, (int, float)):
                mlflow.log_metric(f"calibrator_{key}", float(value))

        gbm_dir = booster_dir / "gbm"
        if gbm_dir.exists():
            for path in sorted(gbm_dir.glob("*.txt")):
                mlflow.log_artifact(str(path), artifact_path="gbm")
        calibrator_dir = booster_dir / "calibrator"
        if calibrator_dir.exists():
            for path in sorted(calibrator_dir.glob("*")):
                if path.is_file():
                    mlflow.log_artifact(str(path), artifact_path="calibrator")

    logger.info("Mirrored train run %s to MLflow (%s)", run_id, uri)
    return {"status": "logged", "run_id": run_id, "tracking_uri": uri}
