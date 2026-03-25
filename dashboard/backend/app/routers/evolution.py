"""Evolution planner router for the Zen Evolution Engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.agents.evolution.manager import (
    EvolutionManager,
    EvolutionPhaseGateError,
    EvolutionRequestNotFoundError,
)
from src.utils.config import get_settings

router = APIRouter()
settings = get_settings()
_manager = EvolutionManager()


class CreateEvolutionRequest(BaseModel):
    message_text: str = Field(min_length=5, max_length=5000)


class AddEvolutionMessageRequest(BaseModel):
    message_text: str = Field(min_length=2, max_length=5000)


class ApprovalRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


def _ensure_dashboard_enabled() -> None:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")


@router.get("/requests")
async def list_requests(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    risk_class: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List recent evolution requests."""
    _ensure_dashboard_enabled()
    return _manager.list_requests(limit=limit, offset=offset, status=status, risk_class=risk_class)


@router.post("/requests")
async def create_request(body: CreateEvolutionRequest, request: Request) -> dict[str, Any]:
    """Create a new operator-requested evolution workflow."""
    _ensure_dashboard_enabled()
    operator = getattr(request.state, "dashboard_operator", None)
    return _manager.create_request(requested_by=operator, message_text=body.message_text)


@router.get("/requests/{request_id}")
async def get_request(request_id: int) -> dict[str, Any]:
    """Return the full request detail, including latest plan and audit trail."""
    _ensure_dashboard_enabled()
    try:
        return _manager.get_request(request_id)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/requests/{request_id}/plan")
async def get_plan(request_id: int) -> dict[str, Any]:
    """Return the latest structured plan for an evolution request."""
    _ensure_dashboard_enabled()
    try:
        return _manager.get_plan(request_id)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/requests/{request_id}/messages")
async def add_message(request_id: int, body: AddEvolutionMessageRequest, request: Request) -> dict[str, Any]:
    """Add a clarification message and regenerate the plan."""
    _ensure_dashboard_enabled()
    operator = getattr(request.state, "dashboard_operator", None)
    try:
        return _manager.add_message(request_id=request_id, message_text=body.message_text, requested_by=operator)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/requests/{request_id}/runs")
async def get_runs(request_id: int) -> list[dict[str, Any]]:
    """Return workflow run records for the request."""
    _ensure_dashboard_enabled()
    try:
        return _manager.list_runs(request_id)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/requests/{request_id}/artifacts")
async def get_artifacts(
    request_id: int,
    artifact_type: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Return persisted planner artifacts such as validation matrices and repo context."""
    _ensure_dashboard_enabled()
    try:
        return _manager.list_artifacts(request_id, artifact_type=artifact_type)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/requests/{request_id}/approve-build")
async def approve_build(request_id: int, body: ApprovalRequest, request: Request):
    """Attempt to approve branch execution. Phase 1 intentionally blocks this."""
    _ensure_dashboard_enabled()
    operator = getattr(request.state, "dashboard_operator", None)
    try:
        return _manager.approve_build(request_id=request_id, requested_by=operator, notes=body.notes)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EvolutionPhaseGateError as exc:
        approval = exc.args[1] if len(exc.args) > 1 else None
        return JSONResponse(
            status_code=409,
            content={
                "status": "blocked",
                "detail": str(exc.args[0]),
                "approval": approval,
            },
        )


@router.post("/requests/{request_id}/approve-deploy")
async def approve_deploy(request_id: int, body: ApprovalRequest, request: Request):
    """Attempt to approve deployment. Phase 1 intentionally blocks this."""
    _ensure_dashboard_enabled()
    operator = getattr(request.state, "dashboard_operator", None)
    try:
        return _manager.approve_deploy(request_id=request_id, requested_by=operator, notes=body.notes)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EvolutionPhaseGateError as exc:
        approval = exc.args[1] if len(exc.args) > 1 else None
        return JSONResponse(
            status_code=409,
            content={
                "status": "blocked",
                "detail": str(exc.args[0]),
                "approval": approval,
            },
        )


@router.get("/requests/{request_id}/deployments")
async def get_deployments(request_id: int) -> list[dict[str, Any]]:
    """Return deployment and rollback records for later evolution phases."""
    _ensure_dashboard_enabled()
    try:
        return _manager.list_deployments(request_id)
    except EvolutionRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
