"""Persistence and orchestration manager for evolution planning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from dashboard.backend.app.services.event_logger import log_event
from src.data.database import get_session
from src.data.models import (
    EvolutionApproval,
    EvolutionArtifact,
    EvolutionDeployment,
    EvolutionMessage,
    EvolutionPlan,
    EvolutionRequest,
    EvolutionRun,
)
from src.utils.logger import get_logger

from .planner import EvolutionPlanner, PlanRecommendation

logger = get_logger("evolution.manager")


class EvolutionRequestNotFoundError(LookupError):
    """Raised when an evolution request cannot be found."""


class EvolutionPhaseGateError(RuntimeError):
    """Raised when Phase 1 blocks build or deploy authority."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class EvolutionManager:
    """Manage request creation, replanning, and phase-gated audit records."""

    def __init__(self, planner: EvolutionPlanner | None = None) -> None:
        self._planner = planner or EvolutionPlanner()

    def list_requests(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        risk_class: str | None = None,
    ) -> list[dict[str, Any]]:
        session = get_session()
        try:
            query = session.query(EvolutionRequest)
            if status:
                query = query.filter(EvolutionRequest.status == status)
            if risk_class:
                query = query.filter(EvolutionRequest.risk_class == risk_class)
            requests = (
                query.order_by(EvolutionRequest.updated_at.desc(), EvolutionRequest.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [self._serialize_request_summary(item) for item in requests]
        finally:
            session.close()

    def create_request(self, *, requested_by: str | None, message_text: str) -> dict[str, Any]:
        session = get_session()
        try:
            request = EvolutionRequest(
                source_channel="dashboard",
                requested_by=requested_by,
                request_text=message_text.strip(),
                status="DRAFT",
            )
            session.add(request)
            session.flush()

            session.add(
                EvolutionMessage(
                    request_id=request.id,
                    role="operator",
                    message_type="request",
                    message_text=message_text.strip(),
                )
            )

            self._replan_request(session, request)
            session.commit()
            payload = self._serialize_request_detail(session, request)
            self._emit_request_event(request)
            return payload
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_request(self, request_id: int) -> dict[str, Any]:
        session = get_session()
        try:
            request = self._load_request(session, request_id)
            return self._serialize_request_detail(session, request)
        finally:
            session.close()

    def get_plan(self, request_id: int) -> dict[str, Any]:
        session = get_session()
        try:
            request = self._load_request(session, request_id)
            return self._serialize_plan(self._latest_plan(session, request.id))
        finally:
            session.close()

    def add_message(self, *, request_id: int, message_text: str, requested_by: str | None) -> dict[str, Any]:
        session = get_session()
        try:
            request = self._load_request(session, request_id)
            session.add(
                EvolutionMessage(
                    request_id=request.id,
                    role="operator",
                    message_type="clarification",
                    message_text=message_text.strip(),
                    metadata_json=_json_dumps({"requested_by": requested_by}),
                )
            )
            self._replan_request(session, request)
            session.commit()
            payload = self._serialize_request_detail(session, request)
            log_event(
                event_type="evolution_request_updated",
                source="evolution",
                message=f"Evolution request {request.id} replanned",
                metadata={"request_id": request.id, "status": request.status},
            )
            return payload
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_runs(self, request_id: int) -> list[dict[str, Any]]:
        session = get_session()
        try:
            self._load_request(session, request_id)
            runs = (
                session.query(EvolutionRun)
                .filter(EvolutionRun.request_id == request_id)
                .order_by(EvolutionRun.started_at.desc(), EvolutionRun.id.desc())
                .all()
            )
            return [self._serialize_run(run) for run in runs]
        finally:
            session.close()

    def list_artifacts(self, request_id: int, artifact_type: str | None = None) -> list[dict[str, Any]]:
        session = get_session()
        try:
            self._load_request(session, request_id)
            query = session.query(EvolutionArtifact).filter(EvolutionArtifact.request_id == request_id)
            if artifact_type:
                query = query.filter(EvolutionArtifact.artifact_type == artifact_type)
            artifacts = query.order_by(EvolutionArtifact.created_at.desc(), EvolutionArtifact.id.desc()).all()
            return [self._serialize_artifact(artifact) for artifact in artifacts]
        finally:
            session.close()

    def approve_build(self, *, request_id: int, requested_by: str | None, notes: str | None = None) -> dict[str, Any]:
        return self._record_phase_gate_block(
            request_id=request_id,
            requested_by=requested_by,
            approval_type="build",
            notes=notes,
            reason="US-1.10 is planner-only. Branch-based implementation starts in US-1.11.",
        )

    def approve_deploy(self, *, request_id: int, requested_by: str | None, notes: str | None = None) -> dict[str, Any]:
        return self._record_phase_gate_block(
            request_id=request_id,
            requested_by=requested_by,
            approval_type="deploy",
            notes=notes,
            reason="US-1.10 is planner-only. Deployment approvals remain locked until later gated phases.",
        )

    def list_deployments(self, request_id: int) -> list[dict[str, Any]]:
        session = get_session()
        try:
            self._load_request(session, request_id)
            deployments = (
                session.query(EvolutionDeployment)
                .filter(EvolutionDeployment.request_id == request_id)
                .order_by(EvolutionDeployment.created_at.desc(), EvolutionDeployment.id.desc())
                .all()
            )
            return [self._serialize_deployment(deployment) for deployment in deployments]
        finally:
            session.close()

    def _record_phase_gate_block(
        self,
        *,
        request_id: int,
        requested_by: str | None,
        approval_type: str,
        notes: str | None,
        reason: str,
    ) -> dict[str, Any]:
        session = get_session()
        try:
            request = self._load_request(session, request_id)
            approval = EvolutionApproval(
                request_id=request.id,
                approval_type=approval_type,
                status="blocked",
                requested_by=requested_by,
                decided_by="policy_engine",
                notes=notes or reason,
                decided_at=datetime.now(timezone.utc),
            )
            session.add(approval)
            session.commit()
            payload = self._serialize_approval(approval)
            log_event(
                event_type="evolution_phase_gate_blocked",
                source="evolution",
                message=f"Evolution request {request.id} blocked at {approval_type} gate",
                metadata={"request_id": request.id, "approval_type": approval_type},
            )
            raise EvolutionPhaseGateError(reason, payload)
        except EvolutionPhaseGateError:
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _replan_request(self, session, request: EvolutionRequest) -> None:
        plan_messages = (
            session.query(EvolutionMessage)
            .filter(EvolutionMessage.request_id == request.id, EvolutionMessage.role == "operator")
            .order_by(EvolutionMessage.created_at.asc(), EvolutionMessage.id.asc())
            .all()
        )
        combined_messages = [message.message_text for message in plan_messages]

        run = EvolutionRun(
            request_id=request.id,
            run_kind="planning",
            status="running",
            worker_label="phase_1_planner",
        )
        session.add(run)
        session.flush()

        recommendation = self._planner.create_plan(combined_messages)
        version = (request.latest_plan_version or 0) + 1
        plan = EvolutionPlan(
            request_id=request.id,
            version=version,
            status=recommendation.status,
            summary=recommendation.summary,
            change_spec_json=_json_dumps(
                {
                    "title": recommendation.title,
                    "objective": recommendation.objective,
                    "touched_areas": recommendation.touched_areas,
                    "excluded_areas": recommendation.excluded_areas,
                    "assumptions": recommendation.assumptions,
                    "clarification_questions": recommendation.clarification_questions,
                    "confidence_score": recommendation.confidence_score,
                    "risk_class": recommendation.risk_class,
                    "risk_reasons": recommendation.risk_reasons,
                }
            ),
            repo_context_json=_json_dumps(recommendation.repo_context),
            implementation_steps_json=_json_dumps(recommendation.implementation_steps),
            validation_matrix_json=_json_dumps(recommendation.validation_matrix),
            risk_policy_json=_json_dumps(recommendation.risk_policy),
            phase_capabilities_json=_json_dumps(recommendation.phase_capabilities),
        )
        session.add(plan)

        request.status = recommendation.status
        request.title = recommendation.title
        request.objective = recommendation.objective
        request.risk_class = recommendation.risk_class
        request.latest_plan_version = version
        request.touched_areas_json = _json_dumps(recommendation.touched_areas)
        request.excluded_areas_json = _json_dumps(recommendation.excluded_areas)
        request.assumptions_json = _json_dumps(recommendation.assumptions)
        request.clarification_questions_json = _json_dumps(recommendation.clarification_questions)
        request.required_validations_json = _json_dumps(recommendation.validation_matrix)
        request.current_run_id = run.id
        request.updated_at = datetime.now(timezone.utc)

        session.add(
            EvolutionArtifact(
                request_id=request.id,
                run_id=run.id,
                artifact_type="validation_matrix",
                title=f"Validation Matrix v{version}",
                content_json=_json_dumps(recommendation.validation_matrix),
            )
        )
        session.add(
            EvolutionArtifact(
                request_id=request.id,
                run_id=run.id,
                artifact_type="repo_context",
                title=f"Repo Context v{version}",
                content_json=_json_dumps(recommendation.repo_context),
            )
        )
        session.add(
            EvolutionArtifact(
                request_id=request.id,
                run_id=run.id,
                artifact_type="plan_summary",
                title=f"Plan Summary v{version}",
                content_json=_json_dumps(
                    {
                        "summary": recommendation.summary,
                        "implementation_steps": recommendation.implementation_steps,
                        "risk_policy": recommendation.risk_policy,
                        "phase_capabilities": recommendation.phase_capabilities,
                    }
                ),
            )
        )
        session.add(
            EvolutionMessage(
                request_id=request.id,
                role="planner",
                message_type="plan_status",
                message_text=self._planner_message(recommendation),
                metadata_json=_json_dumps(
                    {
                        "status": recommendation.status,
                        "risk_class": recommendation.risk_class,
                        "plan_version": version,
                    }
                ),
            )
        )

        run.status = "completed"
        run.summary_json = _json_dumps(
            {
                "plan_version": version,
                "status": recommendation.status,
                "risk_class": recommendation.risk_class,
            }
        )
        run.completed_at = datetime.now(timezone.utc)

    def _planner_message(self, recommendation: PlanRecommendation) -> str:
        if recommendation.status == "NEEDS_CLARIFICATION":
            questions = " ".join(
                f"{index + 1}. {question}" for index, question in enumerate(recommendation.clarification_questions)
            )
            return (
                f"Planner needs clarification. Current risk class: {recommendation.risk_class}. "
                f"Open questions: {questions}"
            )
        return (
            f"Plan ready. Classified as {recommendation.risk_class} risk across "
            f"{', '.join(recommendation.touched_areas) or 'unspecified scope'}. "
            "Phase 1 remains review-only with no build or deploy authority."
        )

    def _emit_request_event(self, request: EvolutionRequest) -> None:
        event_type = "evolution_plan_ready"
        if request.status == "NEEDS_CLARIFICATION":
            event_type = "evolution_needs_clarification"
        log_event(
            event_type=event_type,
            source="evolution",
            message=f"Evolution request {request.id} created",
            metadata={"request_id": request.id, "status": request.status, "risk_class": request.risk_class},
        )

    def _load_request(self, session, request_id: int) -> EvolutionRequest:
        request = session.query(EvolutionRequest).filter(EvolutionRequest.id == request_id).first()
        if not request:
            raise EvolutionRequestNotFoundError(f"Evolution request {request_id} not found")
        return request

    def _latest_plan(self, session, request_id: int) -> EvolutionPlan:
        plan = (
            session.query(EvolutionPlan)
            .filter(EvolutionPlan.request_id == request_id)
            .order_by(EvolutionPlan.version.desc(), EvolutionPlan.id.desc())
            .first()
        )
        if not plan:
            raise EvolutionRequestNotFoundError(f"Evolution request {request_id} has no plan")
        return plan

    def _serialize_request_summary(self, request: EvolutionRequest) -> dict[str, Any]:
        touched_areas = _json_loads(request.touched_areas_json, [])
        clarification_questions = _json_loads(request.clarification_questions_json, [])
        return {
            "id": request.id,
            "status": request.status,
            "title": request.title or f"Evolution request {request.id}",
            "objective": request.objective,
            "risk_class": request.risk_class,
            "requested_by": request.requested_by,
            "source_channel": request.source_channel,
            "touched_areas": touched_areas,
            "open_questions_count": len(clarification_questions),
            "latest_plan_version": request.latest_plan_version,
            "created_at": request.created_at.isoformat() if request.created_at else None,
            "updated_at": request.updated_at.isoformat() if request.updated_at else None,
        }

    def _serialize_request_detail(self, session, request: EvolutionRequest) -> dict[str, Any]:
        plan = self._serialize_plan(self._latest_plan(session, request.id))
        messages = (
            session.query(EvolutionMessage)
            .filter(EvolutionMessage.request_id == request.id)
            .order_by(EvolutionMessage.created_at.asc(), EvolutionMessage.id.asc())
            .all()
        )
        runs = (
            session.query(EvolutionRun)
            .filter(EvolutionRun.request_id == request.id)
            .order_by(EvolutionRun.started_at.desc(), EvolutionRun.id.desc())
            .all()
        )
        artifacts = (
            session.query(EvolutionArtifact)
            .filter(EvolutionArtifact.request_id == request.id)
            .order_by(EvolutionArtifact.created_at.desc(), EvolutionArtifact.id.desc())
            .all()
        )
        approvals = (
            session.query(EvolutionApproval)
            .filter(EvolutionApproval.request_id == request.id)
            .order_by(EvolutionApproval.created_at.desc(), EvolutionApproval.id.desc())
            .all()
        )
        deployments = (
            session.query(EvolutionDeployment)
            .filter(EvolutionDeployment.request_id == request.id)
            .order_by(EvolutionDeployment.created_at.desc(), EvolutionDeployment.id.desc())
            .all()
        )
        return {
            **self._serialize_request_summary(request),
            "request_text": request.request_text,
            "excluded_areas": _json_loads(request.excluded_areas_json, []),
            "assumptions": _json_loads(request.assumptions_json, []),
            "clarification_questions": _json_loads(request.clarification_questions_json, []),
            "required_validations": _json_loads(request.required_validations_json, []),
            "phase_capabilities": plan["phase_capabilities"],
            "latest_plan": plan,
            "messages": [self._serialize_message(message) for message in messages],
            "runs": [self._serialize_run(run) for run in runs],
            "artifacts": [self._serialize_artifact(artifact) for artifact in artifacts],
            "approvals": [self._serialize_approval(approval) for approval in approvals],
            "deployments": [self._serialize_deployment(deployment) for deployment in deployments],
        }

    def _serialize_message(self, message: EvolutionMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "role": message.role,
            "message_type": message.message_type,
            "message_text": message.message_text,
            "metadata": _json_loads(message.metadata_json, {}),
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }

    def _serialize_plan(self, plan: EvolutionPlan) -> dict[str, Any]:
        change_spec = _json_loads(plan.change_spec_json, {})
        return {
            "id": plan.id,
            "version": plan.version,
            "status": plan.status,
            "summary": plan.summary,
            "objective": change_spec.get("objective"),
            "touched_areas": change_spec.get("touched_areas", []),
            "excluded_areas": change_spec.get("excluded_areas", []),
            "assumptions": change_spec.get("assumptions", []),
            "clarification_questions": change_spec.get("clarification_questions", []),
            "confidence_score": change_spec.get("confidence_score"),
            "risk_class": change_spec.get("risk_class"),
            "risk_reasons": change_spec.get("risk_reasons", []),
            "repo_context": _json_loads(plan.repo_context_json, {}),
            "implementation_steps": _json_loads(plan.implementation_steps_json, []),
            "validation_matrix": _json_loads(plan.validation_matrix_json, []),
            "risk_policy": _json_loads(plan.risk_policy_json, {}),
            "phase_capabilities": _json_loads(plan.phase_capabilities_json, {}),
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }

    def _serialize_run(self, run: EvolutionRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "run_kind": run.run_kind,
            "status": run.status,
            "summary": _json_loads(run.summary_json, {}),
            "worker_label": run.worker_label,
            "branch_name": run.branch_name,
            "commit_sha": run.commit_sha,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def _serialize_artifact(self, artifact: EvolutionArtifact) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "run_id": artifact.run_id,
            "artifact_type": artifact.artifact_type,
            "title": artifact.title,
            "content": _json_loads(artifact.content_json, {}),
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        }

    def _serialize_approval(self, approval: EvolutionApproval) -> dict[str, Any]:
        return {
            "id": approval.id,
            "approval_type": approval.approval_type,
            "status": approval.status,
            "requested_by": approval.requested_by,
            "decided_by": approval.decided_by,
            "notes": approval.notes,
            "created_at": approval.created_at.isoformat() if approval.created_at else None,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        }

    def _serialize_deployment(self, deployment: EvolutionDeployment) -> dict[str, Any]:
        return {
            "id": deployment.id,
            "approval_id": deployment.approval_id,
            "environment": deployment.environment,
            "status": deployment.status,
            "deploy_ref": deployment.deploy_ref,
            "rollback_ref": deployment.rollback_ref,
            "metadata": _json_loads(deployment.metadata_json, {}),
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
            "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
        }
