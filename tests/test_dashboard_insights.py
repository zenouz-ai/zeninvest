"""Tests for insights router and auth-protected analytics endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.database import Base as DashboardBase
from dashboard.backend.app.middleware.auth import DashboardSessionMiddleware
from dashboard.backend.app.routers import auth as auth_router
from dashboard.backend.app.routers import insights as insights_router
from dashboard.backend.app.routers import public as public_router
from dashboard.backend.app.services.auth import hash_password
from src.data.database import engine, get_session
from src.data.models import (
    Base,
    CycleContextSnapshot,
    GuidanceSectorScore,
    GuidanceSnapshot,
    StrategyChangeEpisode,
    StrategyChangeEvidence,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DashboardSessionMiddleware)
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(public_router.router, prefix="/api/public")
    app.include_router(insights_router.router, prefix="/api/insights")
    return app


def _seed_data() -> None:
    Base.metadata.create_all(bind=engine)
    DashboardBase.metadata.create_all(bind=engine)
    session = get_session()
    try:
        session.query(StrategyChangeEvidence).delete()
        session.query(StrategyChangeEpisode).delete()
        session.query(CycleContextSnapshot).delete()
        session.query(GuidanceSectorScore).delete()
        session.query(GuidanceSnapshot).delete()
        session.commit()
        guidance = GuidanceSnapshot(
            cycle_id="cycle-1",
            timestamp=datetime.now(timezone.utc),
            mode="active",
            status="active",
            regime="RISK_ON",
            confidence_score=0.8,
            rationale="Constructive backdrop.",
            prompt_summary="Lean into Technology and Industrials.",
            bias_payload_json=json.dumps({"enabled": True}),
            evidence_summary_json=json.dumps({"macro_state_id": 1}),
            raw_payload_json=json.dumps({}),
        )
        session.add(guidance)
        session.flush()
        session.add(
            GuidanceSectorScore(
                guidance_snapshot_id=int(guidance.id),
                sector="Technology",
                score=1.0,
                label="favored",
                rationale="Strong breadth",
                evidence_json=json.dumps(["Strong breadth"]),
            )
        )
        session.add(
            CycleContextSnapshot(
                cycle_id="cycle-1",
                run_type="manual",
                captured_at=datetime.now(timezone.utc),
                guidance_snapshot_id=int(guidance.id),
                guidance_mode="active",
                prompt_guidance_summary="Lean into Technology and Industrials.",
                applied_screening_bias_json=json.dumps({"guidance_applied": True}),
                pre_guidance_candidate_count=10,
                post_guidance_candidate_count=10,
                pre_guidance_sector_distribution_json=json.dumps({"Technology": 2, "Utilities": 2}),
                post_guidance_sector_distribution_json=json.dumps({"Technology": 3, "Utilities": 1}),
                active_strategy_episode_ids_json=json.dumps([1]),
            )
        )
        episode = StrategyChangeEpisode(
            status="confirmed",
            title="Strategy update",
            summary="Adjusted screening posture.",
            change_type="strategy",
            review_confidence=0.8,
            commit_start_sha="abc123",
            commit_end_sha="def456",
            effective_start_at=datetime.now(timezone.utc),
            notes="Observational only",
        )
        session.add(episode)
        session.flush()
        session.add(
            StrategyChangeEvidence(
                episode_id=int(episode.id),
                commit_sha="abc123",
                committed_at=datetime.now(timezone.utc),
                author_name="tester",
                title="Adjust strategy",
                summary="Summary",
                affected_files_json=json.dumps(["src/orchestrator/main.py"]),
                metadata_json=json.dumps({}),
            )
        )
        session.commit()
    finally:
        session.close()


def test_insights_routes_require_auth_and_return_data() -> None:
    with patch.dict(
        "os.environ",
        {
            "DASHBOARD_OPERATOR_USERNAME": "operator",
            "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
            "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
            "DASHBOARD_INSECURE_DEV_MODE": "true",
        },
        clear=False,
    ):
        _seed_data()
        client = TestClient(_make_app(), base_url="http://localhost")

        unauth = client.get("/api/insights/guidance/latest")
        assert unauth.status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "super-secret-password"},
        )
        assert login.status_code == 200

        guidance_resp = client.get("/api/insights/guidance/latest")
        assert guidance_resp.status_code == 200
        assert guidance_resp.json()["regime"] == "RISK_ON"

        impact_resp = client.get("/api/insights/guidance/cycle-impact")
        assert impact_resp.status_code == 200
        assert impact_resp.json()[0]["post_guidance_sector_distribution"]["Technology"] == 3

        episodes_resp = client.get("/api/insights/episodes")
        assert episodes_resp.status_code == 200
        assert episodes_resp.json()[0]["status"] == "confirmed"


def test_public_guidance_routes_are_anonymous_and_sanitized() -> None:
    with patch.dict(
        "os.environ",
        {
            "DASHBOARD_OPERATOR_USERNAME": "operator",
            "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
            "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
            "DASHBOARD_INSECURE_DEV_MODE": "true",
        },
        clear=False,
    ):
        _seed_data()
        client = TestClient(_make_app(), base_url="http://localhost")

        latest_resp = client.get("/api/public/insights/guidance/latest")
        assert latest_resp.status_code == 200
        latest_json = latest_resp.json()
        assert latest_json["regime"] == "RISK_ON"
        assert "sector_scores" in latest_json
        assert "evidence_summary" not in latest_json
        assert "bias_payload" not in latest_json

        history_resp = client.get("/api/public/insights/guidance/history")
        assert history_resp.status_code == 200
        assert len(history_resp.json()) >= 1
