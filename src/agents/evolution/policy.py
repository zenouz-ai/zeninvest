"""Risk and validation policy for the evolution workflow."""

from __future__ import annotations

from typing import Any

AREA_LABELS: dict[str, str] = {
    "dashboard_ui": "Dashboard UI",
    "dashboard_backend": "Dashboard Backend",
    "notifications_reporting": "Notifications & Reporting",
    "trading_logic": "Trading Logic",
    "deployment_infra": "Deployment & Infrastructure",
    "docs": "Documentation & Roadmap",
}

AREA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dashboard_ui": (
        "dashboard",
        "frontend",
        "ui",
        "page",
        "component",
        "react",
        "vite",
        "tailwind",
        "chart",
        "table",
        "layout",
        "copy",
        "label",
        "modal",
    ),
    "dashboard_backend": (
        "backend",
        "api",
        "endpoint",
        "router",
        "fastapi",
        "sse",
        "auth",
        "session",
    ),
    "notifications_reporting": (
        "notification",
        "notifications",
        "alert",
        "alerts",
        "slack",
        "email",
        "report",
        "reporting",
        "summary",
        "digest",
    ),
    "trading_logic": (
        "strategy",
        "trading",
        "trade ",
        "signal",
        "swing",
        "long-term",
        "investing",
        "position sizing",
        "allocation",
        "execution",
        "order",
        "stop-loss",
        "broker",
        "moderation",
        "portfolio logic",
        "risk rules",
    ),
    "deployment_infra": (
        "deploy",
        "deployment",
        "docker",
        "vps",
        "nginx",
        "cloudflare",
        "systemd",
        "github actions",
        "ci",
        "pipeline",
        "secret",
        "credential",
        "infrastructure",
        "branch protection",
        "domain",
    ),
    "docs": (
        "docs",
        "documentation",
        "readme",
        "roadmap",
        "architecture doc",
        "governance",
    ),
}

LOW_RISK_AREAS = {"dashboard_ui", "docs"}
MEDIUM_RISK_AREAS = {"dashboard_backend", "notifications_reporting"}
HIGH_RISK_AREAS = {"trading_logic", "deployment_infra"}


def detect_touched_areas(text: str) -> list[str]:
    """Infer likely repo areas from a natural-language change request."""
    lowered = f" {text.lower()} "
    detected: list[str] = []
    for area, keywords in AREA_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            detected.append(area)
    return detected


def classify_risk(touched_areas: list[str]) -> tuple[str, list[str]]:
    """Classify change risk from inferred areas."""
    if any(area in HIGH_RISK_AREAS for area in touched_areas):
        reasons = [
            "Touches financially sensitive or protected runtime surfaces.",
            "Requires stricter review, quantitative validation, and promotion gates.",
        ]
        return "HIGH", reasons

    if touched_areas and all(area in LOW_RISK_AREAS for area in touched_areas):
        reasons = [
            "Scope is limited to low-risk presentation or documentation surfaces.",
            "Runtime trading behavior is expected to remain unchanged.",
        ]
        return "LOW", reasons

    reasons = [
        "Scope touches backend or operator workflow behavior outside direct trading logic.",
        "Manual review remains appropriate even when the request is not financially sensitive.",
    ]
    return "MEDIUM", reasons


def validation_matrix_for_areas(touched_areas: list[str]) -> list[dict[str, Any]]:
    """Return deterministic validation recommendations for the inferred scope."""
    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, label: str, scope: str, required: bool = True) -> None:
        if any(existing["id"] == check_id for existing in checks):
            return
        checks.append(
            {
                "id": check_id,
                "label": label,
                "scope": scope,
                "required": required,
            }
        )

    if touched_areas == ["docs"] or set(touched_areas) == {"docs"}:
        add_check(
            "docs_review",
            "Documentation review",
            "Verify roadmap/docs stay internally consistent and reflect the shipped behavior.",
        )

    if "dashboard_ui" in touched_areas:
        add_check("frontend_tests", "Frontend unit tests", "Run dashboard frontend unit tests for the affected page or component.")
        add_check("frontend_build", "Frontend build", "Build the dashboard frontend to catch type or route regressions.")
        add_check("page_smoke", "Page smoke checks", "Verify the authenticated dashboard page renders and navigation still works.")

    if "dashboard_backend" in touched_areas:
        add_check("targeted_pytest", "Targeted pytest coverage", "Run backend/router/service tests for the affected dashboard flow.")
        add_check("api_auth_smoke", "API/auth smoke checks", "Verify protected dashboard endpoints still respect operator auth and expected contracts.")

    if "notifications_reporting" in touched_areas:
        add_check("notifications_pytest", "Notifications/reporting tests", "Run targeted tests for alerts, reports, or operator-facing summaries.")
        add_check("dry_run_orchestrator", "Dry-run orchestration check", "Exercise the dry-run path when reporting or notification behavior depends on cycle output.")

    if "trading_logic" in touched_areas:
        add_check("trading_pytest", "Trading-path pytest coverage", "Run targeted tests for strategy, risk, execution, and orchestrator decision flow.")
        add_check("dry_run_cycle", "Dry-run cycle", "Run a dry-run orchestration cycle to verify end-to-end behavior safely.")
        add_check("backtest_cli", "Backtesting CLI", "Run the appropriate backtest configuration before any promotion discussion.")
        add_check("walk_forward", "Walk-forward promotion report", "Require walk-forward evidence before considering promotion.")

    if "deployment_infra" in touched_areas:
        add_check("compose_config", "Deployment config checks", "Validate Docker Compose or runtime configuration before any manual deploy.")
        add_check("health_smoke", "Health smoke checks", "Verify health endpoints and operator access behavior after runtime changes.")

    return checks


def phase_capabilities() -> dict[str, Any]:
    """Capabilities deliberately enabled in Phase 1."""
    return {
        "mode": "PLANNER_ONLY",
        "planning_enabled": True,
        "build_enabled": False,
        "deploy_enabled": False,
        "auto_promote_enabled": False,
        "reason": "US-1.10 stops at scoped planning, validation recommendations, and audit logging.",
    }


def request_policy_summary(risk_class: str, touched_areas: list[str]) -> dict[str, Any]:
    """Per-request policy response used by the planner and UI."""
    future_deploy_gate = "Manual approval required"
    if risk_class == "LOW":
        future_deploy_gate = "Review-first in earlier phases; low-risk auto-promotion only in a later gated phase"
    elif risk_class == "HIGH":
        future_deploy_gate = "Explicit approval plus backtest evidence required; never auto-promoted in early phases"

    return {
        "risk_class": risk_class,
        "touched_areas": [AREA_LABELS[area] for area in touched_areas],
        "phase_1_gate": "Plan-only workflow. Build and deploy approvals stay locked.",
        "future_build_mode": "Branch + review",
        "future_deploy_gate": future_deploy_gate,
        "backtest_required": risk_class == "HIGH",
        "protected_surfaces": [
            AREA_LABELS[area] for area in touched_areas if area in HIGH_RISK_AREAS
        ],
    }

