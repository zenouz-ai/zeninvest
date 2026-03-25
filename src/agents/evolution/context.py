"""Repo-context provider for evolution planning."""

from __future__ import annotations

from typing import Any

from .policy import AREA_LABELS

_BASE_DOCS = [
    {
        "title": "Zen Evolution Engine",
        "path": "docs/ZEN_EVOLUTION_ENGINE.md",
        "reason": "Canonical product and policy framing for the evolution workflow.",
    },
    {
        "title": "Sophistication Roadmap",
        "path": "docs/SOPHISTICATION_ROADMAP.md",
        "reason": "Roadmap source of truth and story ordering.",
    },
    {
        "title": "Solution Architecture",
        "path": "docs/ARCHITECTURE.md",
        "reason": "System topology, state flow, and dashboard/backend boundaries.",
    },
    {
        "title": "Governance",
        "path": "docs/GOVERNANCE.md",
        "reason": "Change-management, rollback, and financial-risk guardrails.",
    },
]

_AREA_CONTEXT: dict[str, dict[str, Any]] = {
    "dashboard_ui": {
        "docs": [
            {
                "title": "Dashboard System",
                "path": "docs/DASHBOARD.md",
                "reason": "Defines operator-facing dashboard behavior and page surface area.",
            },
        ],
        "code_areas": [
            {
                "label": "Dashboard frontend routes and pages",
                "paths": [
                    "dashboard/frontend/src/App.tsx",
                    "dashboard/frontend/src/pages",
                    "dashboard/frontend/src/api/client.ts",
                ],
                "reason": "Primary UI surface for authenticated operator workflows.",
            },
        ],
        "roadmap_items": ["US-1.7", "US-1.10"],
    },
    "dashboard_backend": {
        "docs": [
            {
                "title": "Dashboard System",
                "path": "docs/DASHBOARD.md",
                "reason": "Covers REST, SSE, auth split, and dashboard data flow.",
            },
        ],
        "code_areas": [
            {
                "label": "Dashboard API routers and services",
                "paths": [
                    "dashboard/backend/app/main.py",
                    "dashboard/backend/app/routers",
                    "dashboard/backend/app/services",
                ],
                "reason": "Protected operator APIs and backend orchestration live here.",
            },
        ],
        "roadmap_items": ["US-1.7", "US-7.1", "US-1.10"],
    },
    "notifications_reporting": {
        "docs": [
            {
                "title": "Chat and Commands",
                "path": "docs/CHAT_AND_COMMANDS.md",
                "reason": "Operator-facing notifications, command audit trail, and messaging behavior.",
            },
        ],
        "code_areas": [
            {
                "label": "Notification and reporting modules",
                "paths": [
                    "src/agents/notifications",
                    "src/agents/reporting",
                    "dashboard/backend/app/routers/commands.py",
                ],
                "reason": "Messaging, reporting, and audit surfaces are implemented here.",
            },
        ],
        "roadmap_items": ["US-1.5", "US-1.6", "US-1.10"],
    },
    "trading_logic": {
        "docs": [
            {
                "title": "Backtesting Engine",
                "path": "docs/BACKTESTING.md",
                "reason": "Defines the quantitative release gate for trading-path changes.",
            },
            {
                "title": "Trading System Audit",
                "path": "docs/TRADING_SYSTEM_AUDIT.md",
                "reason": "Highlights sensitive execution and risk surfaces that require hard gates.",
            },
        ],
        "code_areas": [
            {
                "label": "Trading decision and execution path",
                "paths": [
                    "src/orchestrator/main.py",
                    "src/agents/strategy",
                    "src/agents/risk",
                    "src/agents/execution",
                ],
                "reason": "Financially sensitive code paths with deterministic safety rules and promotion gates.",
            },
        ],
        "roadmap_items": ["US-5.1", "US-7.3", "US-7.5"],
    },
    "deployment_infra": {
        "docs": [
            {
                "title": "Deployment",
                "path": "docs/DEPLOYMENT.md",
                "reason": "Current VPS/Docker Compose deployment posture and operational runbooks.",
            },
            {
                "title": "Dashboard Deployment",
                "path": "docs/DASHBOARD_DEPLOYMENT.md",
                "reason": "Dashboard-specific production access model and runtime assumptions.",
            },
        ],
        "code_areas": [
            {
                "label": "Runtime and deployment surfaces",
                "paths": [
                    "docker-compose.yml",
                    "Dockerfile",
                    "deploy",
                ],
                "reason": "Deployment changes must stay constrained and manually reviewed.",
            },
        ],
        "roadmap_items": ["US-7.7", "US-8.1", "US-1.12"],
    },
    "docs": {
        "docs": [
            {
                "title": "README",
                "path": "README.md",
                "reason": "Entry-point documentation and high-level product status.",
            },
        ],
        "code_areas": [
            {
                "label": "Repo documentation",
                "paths": [
                    "README.md",
                    "docs",
                ],
                "reason": "Roadmap and architecture documentation must stay synchronized with shipped behavior.",
            },
        ],
        "roadmap_items": ["US-8.1", "US-1.10"],
    },
}

_REPO_CONSTRAINTS = [
    "Evolution requests are operator-driven and dashboard-first in the current phase.",
    "The evolution workflow must stay separate from the trading chat/session domain.",
    "The current production control plane remains Docker Compose on the VPS.",
    "Financially sensitive changes require stronger validation and manual promotion gates.",
]


class RepoContextProvider:
    """Return deterministic repo context for the inferred scope."""

    def build(self, touched_areas: list[str]) -> dict[str, Any]:
        docs = list(_BASE_DOCS)
        code_areas: list[dict[str, Any]] = []
        related_items: list[str] = ["US-1.10"]
        for area in touched_areas:
            context = _AREA_CONTEXT.get(area)
            if not context:
                continue
            docs.extend(context.get("docs", []))
            code_areas.extend(context.get("code_areas", []))
            related_items.extend(context.get("roadmap_items", []))

        return {
            "touched_areas": [AREA_LABELS[area] for area in touched_areas],
            "docs": self._dedupe_entries(docs, "path"),
            "code_areas": self._dedupe_entries(code_areas, "label"),
            "repo_constraints": _REPO_CONSTRAINTS,
            "related_roadmap_items": list(dict.fromkeys(related_items)),
        }

    def _dedupe_entries(self, entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            value = str(entry.get(key))
            if value in seen:
                continue
            seen.add(value)
            deduped.append(entry)
        return deduped

