"""Authenticated guidance and attribution analytics routes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.agents.attribution import StrategyAttributionService
from src.data.database import get_session
from src.data.models import CycleContextSnapshot, GuidanceSectorScore, GuidanceSnapshot
from src.utils.config import get_settings

from ..schemas import (
    CycleContextSnapshotSchema,
    EpisodeBackfillRequestSchema,
    EpisodeReviewRequestSchema,
    GuidanceSnapshotSchema,
    StrategyChangeEpisodeSchema,
)

router = APIRouter()
settings = get_settings()
_attribution = StrategyAttributionService()


def _ensure_dashboard_enabled() -> None:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")


def _serialize_guidance_snapshot(row: GuidanceSnapshot, sector_rows: list[GuidanceSectorScore]) -> GuidanceSnapshotSchema:
    return GuidanceSnapshotSchema(
        id=int(row.id),
        cycle_id=row.cycle_id,
        timestamp=row.timestamp,
        mode=row.mode,
        status=row.status,
        regime=row.regime,
        confidence_score=float(row.confidence_score or 0.0),
        freshness_hours=row.freshness_hours,
        rationale=row.rationale,
        prompt_summary=row.prompt_summary,
        bias_payload=json.loads(row.bias_payload_json or "{}"),
        evidence_summary=json.loads(row.evidence_summary_json or "{}"),
        sector_scores=[
            {
                "sector": sector_row.sector,
                "score": float(sector_row.score or 0.0),
                "label": sector_row.label,
                "rationale": sector_row.rationale,
                "evidence": json.loads(sector_row.evidence_json or "[]"),
            }
            for sector_row in sector_rows
        ],
    )


def _serialize_cycle_context(row: CycleContextSnapshot) -> CycleContextSnapshotSchema:
    return CycleContextSnapshotSchema(
        cycle_id=row.cycle_id,
        run_type=row.run_type,
        captured_at=row.captured_at,
        repo_sha=row.repo_sha,
        config_hash=row.config_hash,
        strategy_prompt_hash=row.strategy_prompt_hash,
        strategy_fingerprint_hash=row.strategy_fingerprint_hash,
        risk_fingerprint_hash=row.risk_fingerprint_hash,
        execution_fingerprint_hash=row.execution_fingerprint_hash,
        guidance_snapshot_id=row.guidance_snapshot_id,
        guidance_mode=row.guidance_mode,
        prompt_guidance_summary=row.prompt_guidance_summary,
        applied_screening_bias=json.loads(row.applied_screening_bias_json or "{}"),
        pre_guidance_candidate_count=row.pre_guidance_candidate_count,
        post_guidance_candidate_count=row.post_guidance_candidate_count,
        pre_guidance_sector_distribution=json.loads(row.pre_guidance_sector_distribution_json or "{}"),
        post_guidance_sector_distribution=json.loads(row.post_guidance_sector_distribution_json or "{}"),
        active_strategy_episode_ids=json.loads(row.active_strategy_episode_ids_json or "[]"),
    )


@router.get("/guidance/latest", response_model=GuidanceSnapshotSchema | None)
async def get_latest_guidance():
    """Return the most recent persisted guidance snapshot."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        row = session.query(GuidanceSnapshot).order_by(desc(GuidanceSnapshot.timestamp)).first()
        if row is None:
            return None
        sector_rows = (
            session.query(GuidanceSectorScore)
            .filter(GuidanceSectorScore.guidance_snapshot_id == row.id)
            .order_by(GuidanceSectorScore.score.desc(), GuidanceSectorScore.sector.asc())
            .all()
        )
        return _serialize_guidance_snapshot(row, sector_rows)
    finally:
        session.close()


@router.get("/guidance/history", response_model=list[GuidanceSnapshotSchema])
async def get_guidance_history(
    days: int = Query(default=14, ge=1, le=90),
) -> list[GuidanceSnapshotSchema]:
    """Return recent guidance snapshots."""
    _ensure_dashboard_enabled()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        rows = (
            session.query(GuidanceSnapshot)
            .filter(GuidanceSnapshot.timestamp >= cutoff)
            .order_by(desc(GuidanceSnapshot.timestamp))
            .all()
        )
        output: list[GuidanceSnapshotSchema] = []
        for row in rows:
            sector_rows = (
                session.query(GuidanceSectorScore)
                .filter(GuidanceSectorScore.guidance_snapshot_id == row.id)
                .order_by(GuidanceSectorScore.score.desc(), GuidanceSectorScore.sector.asc())
                .all()
            )
            output.append(_serialize_guidance_snapshot(row, sector_rows))
        return output
    finally:
        session.close()


@router.get("/guidance/cycle-impact", response_model=list[CycleContextSnapshotSchema])
async def get_guidance_cycle_impact(
    limit: int = Query(default=30, ge=1, le=100),
) -> list[CycleContextSnapshotSchema]:
    """Return recent cycle context rows with screening impact metadata."""
    _ensure_dashboard_enabled()
    session = get_session()
    try:
        rows = (
            session.query(CycleContextSnapshot)
            .order_by(desc(CycleContextSnapshot.captured_at))
            .limit(limit)
            .all()
        )
        return [_serialize_cycle_context(row) for row in rows]
    finally:
        session.close()


@router.get("/episodes", response_model=list[StrategyChangeEpisodeSchema])
async def list_strategy_episodes() -> list[dict[str, Any]]:
    """Return strategy change episodes."""
    _ensure_dashboard_enabled()
    return _attribution.list_episodes()


@router.get("/episodes/{episode_id}", response_model=StrategyChangeEpisodeSchema)
async def get_strategy_episode(episode_id: int) -> dict[str, Any]:
    """Return a strategy episode detail."""
    _ensure_dashboard_enabled()
    try:
        return _attribution.get_episode_detail(episode_id=episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/episodes/backfill", response_model=list[StrategyChangeEpisodeSchema])
async def backfill_strategy_episodes(body: EpisodeBackfillRequestSchema | None = None) -> list[dict[str, Any]]:
    """Backfill recent strategy-affecting git history into proposed episodes."""
    _ensure_dashboard_enabled()
    request = body or EpisodeBackfillRequestSchema()
    _attribution.backfill_recent_episodes(days=request.days)
    return _attribution.list_episodes()


@router.post("/episodes/{episode_id}/confirm", response_model=StrategyChangeEpisodeSchema)
async def confirm_strategy_episode(episode_id: int, body: EpisodeReviewRequestSchema | None = None) -> dict[str, Any]:
    """Confirm a proposed strategy episode."""
    _ensure_dashboard_enabled()
    payload = body or EpisodeReviewRequestSchema()
    try:
        return _attribution.confirm_episode(
            episode_id=episode_id,
            title=payload.title,
            summary=payload.summary,
            effective_start_at=payload.effective_start_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/episodes/{episode_id}/reject", response_model=StrategyChangeEpisodeSchema)
async def reject_strategy_episode(episode_id: int, body: EpisodeReviewRequestSchema | None = None) -> dict[str, Any]:
    """Reject a proposed strategy episode."""
    _ensure_dashboard_enabled()
    _ = body
    try:
        return _attribution.reject_episode(episode_id=episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
