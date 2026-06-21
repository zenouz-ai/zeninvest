"""Build rejected.parquet for US-6.7 learning pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.learning.dataset.rejection_analysis import (
    analyze_rejections,
    label_rows,
    load_snapshot_rows,
    write_analysis_artifacts,
)
from src.learning.spec import DATASET_VERSION, get_default_spec
from src.utils.logger import get_logger

logger = get_logger("learning.dataset.rejected_builder")


def _parquet_dir() -> Path:
    import os

    root = Path(os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT", "data/learning"))
    return root / "parquet" / DATASET_VERSION


def build_rejected_parquet(session: Session) -> dict[str, Any]:
    """Label rejected snapshots and write rejected.parquet + analysis artifacts."""
    spec = get_default_spec()
    rows = load_snapshot_rows(session, is_tradable=False)
    if not rows:
        return {"rows": 0, "parquet_path": None}

    labeled = label_rows(session, rows, spec=spec)
    out_dir = _parquet_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "rejected.parquet"
    labeled.to_parquet(parquet_path, index=False)

    analysis = analyze_rejections(session, spec=spec)
    artifacts = write_analysis_artifacts(analysis)

    logger.info(
        "Rejected dataset built: %s rows -> %s; analysis %s",
        len(labeled),
        parquet_path,
        artifacts.get("json"),
    )
    return {
        "rows": len(labeled),
        "resolved": int(labeled["cf_label"].notna().sum()),
        "parquet_path": str(parquet_path),
        "analysis_artifact": artifacts.get("json"),
        "funnel_metrics": analysis.funnel_metrics,
    }


def run_rejection_analysis_job() -> dict[str, Any]:
    """Entry point for scheduler / CLI."""
    session = get_session()
    try:
        return build_rejected_parquet(session)
    finally:
        session.close()
