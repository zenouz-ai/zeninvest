"""Deterministic planner for the Zen Evolution Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context import RepoContextProvider
from .intent_normalizer import IntentNormalizer
from .policy import AREA_LABELS, phase_capabilities, request_policy_summary, validation_matrix_for_areas

_IMPLEMENTATION_TEMPLATES: dict[str, str] = {
    "dashboard_ui": "Update authenticated dashboard routes, API bindings, and operator-facing UI components for the requested behavior.",
    "dashboard_backend": "Add or adjust dashboard backend endpoints and planner services while preserving operator-session protections.",
    "notifications_reporting": "Extend notification or reporting logic with deterministic audit behavior and operator-visible summaries.",
    "trading_logic": "Scope any trading-path changes to the smallest possible set of strategy, risk, or execution modules and preserve hard control gates.",
    "deployment_infra": "Keep runtime and deployment changes constrained to reviewed infrastructure surfaces with no direct promotion authority.",
    "docs": "Update roadmap and supporting documentation so the shipped evolution workflow stays consistent with repo guidance.",
}


@dataclass(slots=True)
class PlanRecommendation:
    """Structured planning result returned to the manager/router/UI."""

    title: str
    status: str
    objective: str
    summary: str
    touched_areas: list[str]
    excluded_areas: list[str]
    assumptions: list[str]
    clarification_questions: list[str]
    confidence_score: float
    risk_class: str
    risk_reasons: list[str]
    implementation_steps: list[str]
    validation_matrix: list[dict[str, Any]]
    repo_context: dict[str, Any]
    risk_policy: dict[str, Any]
    phase_capabilities: dict[str, Any]


class EvolutionPlanner:
    """Combine normalization, repo context, and policy into a scoped plan."""

    def __init__(
        self,
        normalizer: IntentNormalizer | None = None,
        repo_context: RepoContextProvider | None = None,
    ) -> None:
        self._normalizer = normalizer or IntentNormalizer()
        self._repo_context = repo_context or RepoContextProvider()

    def create_plan(self, messages: list[str]) -> PlanRecommendation:
        normalized = self._normalizer.normalize(messages)
        repo_context = self._repo_context.build(normalized.touched_areas)
        validations = validation_matrix_for_areas(normalized.touched_areas)
        status = "NEEDS_CLARIFICATION" if normalized.clarification_questions else "PLANNED"
        touched_labels = [AREA_LABELS[area] for area in normalized.touched_areas]
        summary = self._build_summary(
            status=status,
            objective=normalized.objective,
            touched_labels=touched_labels,
            risk_class=normalized.risk_class,
        )
        implementation_steps = self._build_steps(normalized.touched_areas, status)

        return PlanRecommendation(
            title=normalized.title,
            status=status,
            objective=normalized.objective,
            summary=summary,
            touched_areas=touched_labels,
            excluded_areas=normalized.excluded_areas,
            assumptions=normalized.assumptions,
            clarification_questions=normalized.clarification_questions,
            confidence_score=normalized.confidence_score,
            risk_class=normalized.risk_class,
            risk_reasons=normalized.risk_reasons,
            implementation_steps=implementation_steps,
            validation_matrix=validations,
            repo_context=repo_context,
            risk_policy=request_policy_summary(normalized.risk_class, normalized.touched_areas),
            phase_capabilities=phase_capabilities(),
        )

    def _build_summary(
        self,
        *,
        status: str,
        objective: str,
        touched_labels: list[str],
        risk_class: str,
    ) -> str:
        scope = ", ".join(touched_labels) if touched_labels else "an unspecified subsystem"
        if status == "NEEDS_CLARIFICATION":
            return (
                f"Planner found a plausible direction for '{objective}' touching {scope}, "
                f"but it needs clarification before the request can move beyond a reviewable plan. "
                f"Current risk class: {risk_class}."
            )
        return (
            f"Scoped evolution plan ready for '{objective}'. "
            f"The request touches {scope} and is classified as {risk_class} risk. "
            "Phase 1 stops at planning, validation recommendations, and audit logging."
        )

    def _build_steps(self, touched_areas: list[str], status: str) -> list[str]:
        steps: list[str] = []
        if status == "NEEDS_CLARIFICATION":
            steps.append("Resolve the open clarification questions before a future branch runner is allowed to act on the request.")

        if not touched_areas:
            steps.append("Identify the primary subsystem before generating implementation work.")
        else:
            for area in touched_areas:
                template = _IMPLEMENTATION_TEMPLATES.get(area)
                if template:
                    steps.append(template)

        steps.append("Attach the scoped plan, repo context, control gates, and validation matrix to the evolution audit trail.")
        return steps

