"""Tests for memory API routes (US-6.2 / US-6.4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.middleware.auth import DashboardSessionMiddleware
from dashboard.backend.app.routers import auth as auth_router
from dashboard.backend.app.routers import memory as memory_router
from dashboard.backend.app.services.auth import hash_password


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DashboardSessionMiddleware)
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(memory_router.router, prefix="/api/memory")
    return app


@pytest.fixture
def dashboard_env():
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
        yield


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "super-secret-password"},
    )
    assert resp.status_code == 200, resp.text


def test_memory_similar_requires_auth(dashboard_env):
    client = TestClient(_make_app(), base_url="http://localhost")
    resp = client.get("/api/memory/similar", params={"q": "momentum thesis"})
    assert resp.status_code == 401


def test_memory_similar_returns_hits(dashboard_env):
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    with patch(
        "dashboard.backend.app.routers.memory.find_similar_cases",
        return_value=[{"doc_id": "d1", "score": 0.9}],
    ):
        resp = client.get("/api/memory/similar", params={"q": "momentum thesis"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["hits"][0]["doc_id"] == "d1"


def test_memory_graph_sector_regime(dashboard_env):
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    with patch(
        "dashboard.backend.app.routers.memory.query_similar_sector_regime",
        return_value=[{"ticker": "AAPL_US_EQ", "label": "big_winner", "pnl_pct": 10.0}],
    ):
        resp = client.get(
            "/api/memory/graph/sector-regime",
            params={"sector": "Technology", "regime": "RISK_ON"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["decisions"][0]["label"] == "big_winner"
