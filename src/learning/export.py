"""Orchestrate audit + build + memory export for scheduler and CLI."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data.database import get_session
from src.data.models import LearningExportRun
from src.learning.audit import run_audit
from src.learning.dataset.builder import DatasetBuilder
from src.learning.spec import get_default_spec
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.export")


def run_learning_export(
    *,
    project_root: str | Path | None = None,
    run_id: str | None = None,
    write_audit_json: bool = True,
) -> dict[str, Any]:
    """Audit, build v2 parquet/text sidecar, and persist export metadata."""
    settings = get_settings()
    spec = get_default_spec()
    if settings.learning_export_dataset_version:
        from src.learning.spec import DatasetSpec

        spec = DatasetSpec(version=settings.learning_export_dataset_version)

    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    run_id = run_id or datetime.now(timezone.utc).strftime("export-%Y%m%dT%H%M%SZ")
    started = time.monotonic()
    status = "completed"
    error_message: str | None = None
    result_dict: dict[str, Any] = {}

    try:
        audit = run_audit()
        if write_audit_json:
            audit_path = root / "data" / "learning" / f"audit_{datetime.now(timezone.utc):%Y%m%d}.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps(audit.to_dict(), indent=2, default=str))

        with DatasetBuilder(project_root=str(root), spec=spec) as builder:
            build_result = builder.build(write=True)

        result_dict = build_result.to_dict()
        result_dict["audit"] = audit.to_dict()
        result_dict["run_id"] = run_id
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        logger.exception("Learning export failed: %s", exc)
        result_dict = {"run_id": run_id, "status": status, "error": error_message}
    finally:
        duration = time.monotonic() - started
        _record_export_run(
            run_id=run_id,
            dataset_version=spec.version,
            status=status,
            rows=int(result_dict.get("decisions_rows", 0) or 0),
            text_corpus_rows=int(result_dict.get("text_corpus_rows", 0) or 0),
            label_distribution=result_dict.get("label_distribution") or {},
            paths=result_dict.get("paths") or {},
            checksum=result_dict.get("checksum"),
            duration_sec=duration,
            error_message=error_message,
        )

    logger.info(
        "Learning export %s completed in %.1fs (%s rows, %s text rows)",
        run_id,
        duration,
        result_dict.get("decisions_rows"),
        result_dict.get("text_corpus_rows"),
    )
    if status == "failed":
        return result_dict
    return result_dict


def _record_export_run(
    *,
    run_id: str,
    dataset_version: str,
    status: str,
    rows: int,
    text_corpus_rows: int,
    label_distribution: dict[str, Any],
    paths: dict[str, str],
    checksum: str | None,
    duration_sec: float,
    error_message: str | None,
) -> None:
    session = get_session()
    try:
        existing = session.query(LearningExportRun).filter(LearningExportRun.run_id == run_id).first()
        payload = {
            "dataset_version": dataset_version,
            "status": status,
            "rows": rows,
            "text_corpus_rows": text_corpus_rows,
            "label_distribution_json": json.dumps(label_distribution, default=str),
            "artifact_paths_json": json.dumps(paths, default=str),
            "checksum": checksum,
            "duration_sec": duration_sec,
            "error_message": error_message,
        }
        if existing is not None:
            for key, value in payload.items():
                setattr(existing, key, value)
        else:
            session.add(LearningExportRun(run_id=run_id, **payload))
        session.commit()
    except Exception as exc:  # pragma: no cover
        session.rollback()
        logger.warning("Failed to persist learning_export_runs row: %s", exc)
    finally:
        session.close()
