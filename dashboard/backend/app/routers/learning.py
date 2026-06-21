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
import os
from datetime import datetime, timedelta, timezone
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


def _learning_root() -> Path:
    """Project root for learning artifacts, honoring INVESTMENT_AGENT_LEARNING_ROOT.

    Mirrors how ``src/learning/cli.py`` resolves its artifact root so the
    dashboard reads from the same directory tests/sandboxes redirect to.
    """
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    return Path(override) if override else _project_root()


def _learning_reports_dir() -> Path:
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override) / "reports"
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
        "is_champion": bool(row.is_champion),
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


def _export_age_days(created_at: datetime | None) -> int | None:
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - created_at).days)


def _serialize_export_row(row: LearningExportRun) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "run_id": row.run_id,
        "dataset_version": row.dataset_version,
        "status": row.status,
        "rows": int(row.rows or 0),
        "text_corpus_rows": int(row.text_corpus_rows or 0),
        "checksum": row.checksum,
        "duration_sec": row.duration_sec,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "artifact_paths": (
            json.loads(row.artifact_paths_json) if row.artifact_paths_json else {}
        ),
    }


def _serialize_train_run(row: LearningRun) -> dict[str, Any]:
    return {
        "run_id": row.run_id,
        "dataset_version": row.dataset_version,
        "status": row.status,
        "is_champion": bool(row.is_champion),
        "rows": int(row.rows or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/status")
async def get_learning_page_status() -> dict[str, Any]:
    """Aggregate north-star, artifact freshness, and gate context for the Learning page."""
    _ensure_dashboard_enabled()
    from src.agents.reporting.north_star_metrics import compute_north_star_metrics
    from src.agents.reporting.realized_trades import realized_trade_outcomes_query
    from src.learning.evaluation.outcome_join import shadow_summary
    from src.learning.spec import DATASET_VERSION

    session = get_session()
    warnings: list[str] = []
    try:
        dataset_version = DATASET_VERSION
        versions = list_dataset_versions(_project_root())
        if versions:
            dataset_version = versions[-1]

        outcome_rows = realized_trade_outcomes_query(session).all()
        north_star = compute_north_star_metrics(outcome_rows, window_days=90).to_dict()

        latest_export_row = (
            session.query(LearningExportRun)
            .order_by(desc(LearningExportRun.created_at))
            .first()
        )
        latest_export = (
            _serialize_export_row(latest_export_row) if latest_export_row else None
        )

        latest_eval_row = (
            session.query(LearningEvaluationRun)
            .order_by(desc(LearningEvaluationRun.created_at))
            .first()
        )
        latest_evaluation = None
        if latest_eval_row is not None:
            metrics = json.loads(latest_eval_row.metrics_json) if latest_eval_row.metrics_json else {}
            gates = json.loads(latest_eval_row.gates_json) if latest_eval_row.gates_json else {}
            report_path = (
                _project_root() / "data" / "learning" / "evaluation" / latest_eval_row.run_id / "index.html"
            )
            latest_evaluation = {
                "run_id": latest_eval_row.run_id,
                "dataset_version": latest_eval_row.dataset_version,
                "status": latest_eval_row.status,
                "n_rows": latest_eval_row.n_rows,
                "closed_trades": latest_eval_row.closed_trades,
                "created_at": (
                    latest_eval_row.created_at.isoformat() if latest_eval_row.created_at else None
                ),
                "metrics": metrics,
                "gates": gates,
                "report_available": report_path.exists(),
            }

        latest_train_row = (
            session.query(LearningRun)
            .filter(
                LearningRun.status == "completed",
                LearningRun.dataset_version == dataset_version,
            )
            .order_by(desc(LearningRun.is_champion), desc(LearningRun.created_at))
            .first()
        )
        latest_train_run = (
            _serialize_train_run(latest_train_row) if latest_train_row else None
        )

        export_preview_rows = (
            session.query(LearningExportRun)
            .order_by(desc(LearningExportRun.created_at))
            .limit(10)
            .all()
        )
        exports_preview = [_serialize_export_row(r) for r in export_preview_rows]

        if latest_export is None:
            warnings.append(
                "No weekly export recorded — run: poetry run python -m src.learning.cli run-export"
            )
        else:
            export_age = _export_age_days(latest_export_row.created_at if latest_export_row else None)
            if export_age is not None and export_age > 8:
                warnings.append(
                    f"Parquet export is {export_age} days old (>8d) — schedule may have missed a week"
                )

        if latest_export is not None and latest_evaluation is None:
            warnings.append(
                "Export exists but no evaluation run — run: poetry run python -m src.learning.cli evaluate"
            )

        shadow = shadow_summary(days=30)

        from src.learning.dataset.rejection_analysis import rejection_analysis_freshness

        rejection_freshness = rejection_analysis_freshness()

        return {
            "north_star": north_star,
            "dataset_version": dataset_version,
            "latest_export": latest_export,
            "latest_evaluation": latest_evaluation,
            "latest_train_run": latest_train_run,
            "shadow_summary": shadow,
            "exports_preview": exports_preview,
            "rejection_analysis": rejection_freshness,
            "staleness_warnings": warnings,
        }
    finally:
        session.close()


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
        out = [_serialize_export_row(r) for r in rows]
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


@router.get("/rejection-analysis")
async def get_rejection_analysis() -> dict[str, Any]:
    """Serve the most recent precomputed rejected-ticker analysis artifact.

    Reads ``data/learning/reports/rejected_analysis_<YYYYMMDD>.json`` (produced
    by ``scripts/analyze_rejected_tickers.py``) and returns it verbatim plus
    ``artifact_name``/``artifact_mtime``. Never computes forward returns at
    request time. Returns ``{"available": False, ...}`` when no artifact exists.
    """
    _ensure_dashboard_enabled()
    reports_dir = _learning_reports_dir()
    candidates = (
        sorted(reports_dir.glob("rejected_analysis_*.json")) if reports_dir.exists() else []
    )
    if not candidates:
        return {
            "available": False,
            "hint": "run poetry run python scripts/analyze_rejected_tickers.py",
        }
    latest = candidates[-1]  # filename date sorts lexicographically
    try:
        payload = json.loads(latest.read_text())
    except json.JSONDecodeError:
        return {
            "available": False,
            "hint": "rejected_analysis artifact is corrupt — re-run scripts/analyze_rejected_tickers.py",
        }
    payload["artifact_name"] = latest.name
    payload["artifact_mtime"] = datetime.fromtimestamp(
        latest.stat().st_mtime, tz=timezone.utc
    ).isoformat()
    from src.learning.dataset.rejection_analysis import load_rejection_history

    payload["history"] = load_rejection_history(directory=reports_dir)
    return payload


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


@router.get("/evaluation/committee")
async def get_committee_evaluation() -> dict[str, Any]:
    """Committee attribution + context influence from latest evaluation run."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        row = (
            session.query(LearningEvaluationRun)
            .order_by(desc(LearningEvaluationRun.created_at))
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="no evaluation runs")
        metrics = json.loads(row.metrics_json) if row.metrics_json else {}
        return {
            "run_id": row.run_id,
            "committee": metrics.get("committee") or {},
            "context_influence": metrics.get("context_influence") or {},
            "policies": {
                k: v
                for k, v in (metrics.get("policies") or {}).items()
                if k.startswith(("baseline_strategy", "challenger_moderation", "challenger_gpt", "challenger_gemini", "challenger_risk", "champion_as_is"))
            },
        }
    finally:
        session.close()


@router.get("/committee/debate")
async def get_committee_debate_health(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """Live committee-debate leading indicators (ungated; no closed-trade gate).

    Churn rate, participation, rounds/consensus mix, per-moderator churn, skeptic tool usage,
    and moderation spend over the window — answers "is the debate doing anything, at what cost?"
    before there are enough closed trades for forward-outcome attribution.
    """
    _ensure_dashboard_enabled()
    from src.learning.evaluation.committee_attribution import compute_debate_health

    return compute_debate_health(days=days)


@router.get("/evaluation/research")
async def get_research_evaluation() -> dict[str, Any]:
    """Research influence attribution from latest evaluation run."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        row = (
            session.query(LearningEvaluationRun)
            .order_by(desc(LearningEvaluationRun.created_at))
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="no evaluation runs")
        metrics = json.loads(row.metrics_json) if row.metrics_json else {}
        return {
            "run_id": row.run_id,
            "research_influence": metrics.get("research_influence") or {},
            "policies": {
                k: v
                for k, v in (metrics.get("policies") or {}).items()
                if k.startswith(("challenger_no_research", "challenger_skeptic_research", "champion_as_is"))
            },
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


@router.get("/shadow/entry-advisory")
async def get_shadow_entry_advisory(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """Shadow stall/loser probability advisory for recent BUY scores (no live influence)."""
    _ensure_dashboard_enabled()
    from src.learning.evaluation.outcome_join import entry_advisory_summary

    return entry_advisory_summary(days=days)


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
