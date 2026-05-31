"""Authenticated routes for the trade-outcome learning pipeline.

Surfaces ``learning_runs`` rows and the on-disk report bundle so the
dashboard's LearningInsights page can render calibration, GBM and stall
diagnostics without touching the SQLite tables directly.

All routes are read-only and gated behind the same session middleware as the
rest of the private dashboard surface (`DashboardSessionMiddleware`). The
``dashboard_enabled`` setting is checked on every call so the surface
disappears cleanly when the dashboard is turned off in config.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import desc

from dashboard.backend.app.services.learning_datasets import (
    dataset_manifest,
    is_safe_version,
    list_dataset_versions,
    preview_memory_bundle,
    preview_parquet,
    read_json_artifact,
    resolve_download_path,
)

from src.data.database import get_session
from src.data.models import LearningEvaluationRun, LearningExportRun, LearningRun, DecisionShadowScore
from src.utils.config import get_settings

router = APIRouter()
settings = get_settings()


def _project_root() -> Path:
    """Resolve the repo root (4 levels up from this file)."""
    return Path(__file__).resolve().parents[4]


def _reports_root() -> Path:
    return _project_root() / "data" / "learning" / "reports"


def _ensure_dashboard_enabled() -> None:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")


def _serialize_run(row: LearningRun) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "run_id": row.run_id,
        "dataset_version": row.dataset_version,
        "model_kind": row.model_kind,
        "status": row.status,
        "rows": int(row.rows or 0),
        "checksum": row.checksum,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "label_distribution": (
            json.loads(row.label_distribution_json) if row.label_distribution_json else {}
        ),
        "artifact_paths": (
            json.loads(row.artifact_paths_json) if row.artifact_paths_json else {}
        ),
    }


@router.get("/exports")
async def list_exports(
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Return recent weekly dataset export runs."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        rows = (
            session.query(LearningExportRun)
            .order_by(desc(LearningExportRun.created_at))
            .limit(limit)
            .all()
        )
        out = [
            {
                "id": int(r.id),
                "run_id": r.run_id,
                "dataset_version": r.dataset_version,
                "status": r.status,
                "rows": int(r.rows or 0),
                "text_corpus_rows": int(r.text_corpus_rows or 0),
                "checksum": r.checksum,
                "duration_sec": r.duration_sec,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "artifact_paths": (
                    json.loads(r.artifact_paths_json) if r.artifact_paths_json else {}
                ),
            }
            for r in rows
        ]
        return {"exports": out, "count": len(out)}
    finally:
        session.close()


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=25, ge=1, le=100),
    status: str | None = Query(default=None),
    dataset_version: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return the most recent ``learning_runs`` rows (paginated)."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        q = session.query(LearningRun).order_by(desc(LearningRun.created_at))
        if status:
            q = q.filter(LearningRun.status == status)
        if dataset_version:
            q = q.filter(LearningRun.dataset_version == dataset_version)
        rows = q.limit(limit).all()
        return {"runs": [_serialize_run(r) for r in rows], "count": len(rows)}
    finally:
        session.close()


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Return one run plus the full ``metrics.json`` payload (if present)."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        row = session.query(LearningRun).filter(LearningRun.run_id == run_id).first()
    finally:
        session.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"learning run not found: {run_id}")
    serialized = _serialize_run(row)
    metrics_path = _reports_root() / run_id / "metrics.json"
    metrics_payload: dict[str, Any] | None = None
    if metrics_path.exists():
        try:
            metrics_payload = json.loads(metrics_path.read_text())
        except json.JSONDecodeError:
            metrics_payload = None
    insights_dir = _reports_root() / run_id / "insights"
    insight_files: list[str] = []
    if insights_dir.exists():
        insight_files = sorted(p.name for p in insights_dir.glob("*.png"))
    return {
        "run": serialized,
        "metrics": metrics_payload,
        "insight_files": insight_files,
        "report_available": (_reports_root() / run_id / "index.html").exists(),
    }


@router.get("/runs/{run_id}/report", include_in_schema=False)
async def get_run_report(run_id: str) -> FileResponse:
    """Serve the static ``index.html`` for a run as raw HTML."""
    _ensure_dashboard_enabled()
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    path = _reports_root() / run_id / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"report not found for run {run_id}")
    return FileResponse(path, media_type="text/html")


@router.get("/runs/{run_id}/insights/{filename}", include_in_schema=False)
async def get_run_insight(run_id: str, filename: str) -> FileResponse:
    """Serve a single insight PNG.

    The ``filename`` must be a plain ``*.png`` name with no path
    separators — anything else returns 400. Any file outside
    ``data/learning/reports/<run_id>/insights/`` is also rejected so
    operators can't traverse out of the report bundle.
    """
    _ensure_dashboard_enabled()
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="only .png is served")
    insights_dir = (_reports_root() / run_id / "insights").resolve()
    path = (insights_dir / filename).resolve()
    if insights_dir not in path.parents and path != insights_dir:
        # Defence-in-depth: resolve() neutralises any traversal attempt.
        raise HTTPException(status_code=400, detail="invalid filename")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"insight not found: {filename}")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "image/png")


@router.get("/runs/{run_id}/audit")
async def get_run_audit(run_id: str) -> dict[str, Any]:
    """Return any companion ``audit_*.json`` payload that lives alongside the bundle."""
    _ensure_dashboard_enabled()
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    audit_dir = _project_root() / "data" / "learning"
    # Match either a per-run or the canonical Mar 5 -> May 12 audit file.
    candidate_names = (f"audit_{run_id}.json", "audit_20260512.json", "audit.json")
    for name in candidate_names:
        path = audit_dir / name
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
    raise HTTPException(status_code=404, detail="audit payload not available")


def _is_safe_run_id(run_id: str) -> bool:
    """Allow alphanumeric, ``_`` and ``-`` only. Mirrors how the CLI builds IDs."""
    return bool(run_id) and all(c.isalnum() or c in "_-." for c in run_id) and ".." not in run_id


@router.get("/datasets/versions")
async def list_dataset_versions_route() -> dict[str, Any]:
    """List on-disk learning dataset versions (e.g. v1, v2)."""
    _ensure_dashboard_enabled()
    versions = list_dataset_versions(_project_root())
    return {"versions": versions, "default": versions[-1] if versions else None}


@router.get("/datasets/{version}")
async def get_dataset_manifest(version: str) -> dict[str, Any]:
    """Manifest of parquet / JSONL artifacts for one dataset version."""
    _ensure_dashboard_enabled()
    if not is_safe_version(version):
        raise HTTPException(status_code=400, detail="invalid version")
    try:
        return dataset_manifest(_project_root(), version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/datasets/{version}/preview/{artifact}")
async def preview_dataset_artifact(
    version: str,
    artifact: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Paginated JSON preview of a parquet artifact or memory_bundle."""
    _ensure_dashboard_enabled()
    if not is_safe_version(version):
        raise HTTPException(status_code=400, detail="invalid version")
    root = _project_root()
    try:
        if artifact == "memory_bundle":
            return preview_memory_bundle(root, version, offset=offset, limit=limit)
        return preview_parquet(root, version, artifact, offset=offset, limit=limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/datasets/{version}/json/{artifact}")
async def get_dataset_json_artifact(version: str, artifact: str) -> Any:
    """Return schema.json or splits.json contents."""
    _ensure_dashboard_enabled()
    if not is_safe_version(version):
        raise HTTPException(status_code=400, detail="invalid version")
    try:
        return read_json_artifact(_project_root(), version, artifact)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{artifact} not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/datasets/{version}/download/{filename}", include_in_schema=False)
async def download_dataset_file(version: str, filename: str) -> FileResponse:
    """Download a raw dataset file (parquet, json, jsonl)."""
    _ensure_dashboard_enabled()
    if not is_safe_version(version):
        raise HTTPException(status_code=400, detail="invalid version")
    try:
        path = resolve_download_path(_project_root(), version, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"file not found: {filename}")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream", filename=filename)


@router.get("/audit/latest")
async def get_latest_audit() -> dict[str, Any]:
    """Return the most recent audit_*.json from data/learning/."""
    _ensure_dashboard_enabled()
    audit_dir = _project_root() / "data" / "learning"
    if not audit_dir.exists():
        raise HTTPException(status_code=404, detail="no audit files")
    files = sorted(audit_dir.glob("audit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="no audit files")
    try:
        payload = json.loads(files[0].read_text())
        payload["_filename"] = files[0].name
        return payload
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="audit file corrupt") from exc


@router.get("/evaluation/latest")
async def get_latest_evaluation() -> dict[str, Any]:
    """Return the most recent champion/challenger evaluation."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        row = (
            session.query(LearningEvaluationRun)
            .order_by(desc(LearningEvaluationRun.created_at))
            .first()
        )
        if row is None:
            eval_dir = _project_root() / "data" / "learning" / "evaluation"
            if eval_dir.exists():
                dirs = sorted(eval_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                for d in dirs:
                    metrics_path = d / "metrics.json"
                    if metrics_path.exists():
                        payload = json.loads(metrics_path.read_text())
                        payload["report_available"] = (d / "index.html").exists()
                        return payload
            raise HTTPException(status_code=404, detail="no evaluation runs")
        metrics = json.loads(row.metrics_json) if row.metrics_json else {}
        gates = json.loads(row.gates_json) if row.gates_json else {}
        report_path = _project_root() / "data" / "learning" / "evaluation" / row.run_id / "index.html"
        return {
            "run_id": row.run_id,
            "dataset_version": row.dataset_version,
            "status": row.status,
            "n_rows": row.n_rows,
            "closed_trades": row.closed_trades,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "metrics": metrics,
            "gates": gates,
            "report_available": report_path.exists(),
        }
    finally:
        session.close()


@router.get("/evaluation/{run_id}/report", include_in_schema=False)
async def get_evaluation_report(run_id: str) -> FileResponse:
    """Serve evaluation HTML report."""
    _ensure_dashboard_enabled()
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    path = _project_root() / "data" / "learning" / "evaluation" / run_id / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return FileResponse(path, media_type="text/html")


@router.get("/shadow/summary")
async def get_shadow_summary(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """Aggregate shadow scoring summary."""
    _ensure_dashboard_enabled()
    from src.learning.evaluation.outcome_join import shadow_summary

    return shadow_summary(days=days)


@router.get("/shadow/disagreements")
async def get_shadow_disagreements(
    limit: int = Query(default=50, ge=1, le=200),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """Rows where challenger recommended action differs from champion."""
    _ensure_dashboard_enabled()
    from datetime import datetime, timedelta, timezone

    session = get_session()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        rows = (
            session.query(DecisionShadowScore)
            .filter(
                DecisionShadowScore.decision_ts >= cutoff,
                DecisionShadowScore.recommended_action != DecisionShadowScore.champion_action,
            )
            .order_by(desc(DecisionShadowScore.decision_ts))
            .limit(limit)
            .all()
        )
        out = [
            {
                "cycle_id": r.cycle_id,
                "ticker": r.ticker,
                "decision_ts": r.decision_ts.isoformat() if r.decision_ts else None,
                "policy_id": r.policy_id,
                "champion_action": r.champion_action,
                "recommended_action": r.recommended_action,
                "scores": json.loads(r.scores_json) if r.scores_json else {},
                "outcome": json.loads(r.outcome_json) if r.outcome_json else None,
            }
            for r in rows
        ]
        return {"disagreements": out, "count": len(out)}
    finally:
        session.close()
