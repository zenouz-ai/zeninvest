"""Tests for dashboard operator session auth."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from dashboard.backend.app.middleware.auth import DashboardSessionMiddleware
from dashboard.backend.app.routers import auth as auth_router
from dashboard.backend.app.services.auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    hash_password,
    require_dashboard_auth_config,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DashboardSessionMiddleware)
    app.include_router(auth_router.router, prefix="/api/auth")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/public/ping")
    async def public_ping():
        return {"public": True}

    @app.get("/api/public/performance/metrics")
    async def public_performance_metrics():
        return {"public": True, "scope": "performance"}

    @app.get("/api/public/portfolio")
    async def public_portfolio():
        return {"public": True, "scope": "portfolio"}

    @app.get("/api/public/macro/state")
    async def public_macro_state():
        return {"public": True, "scope": "macro"}

    @app.get("/api/private")
    async def private_ping(request: Request):
        return {"operator": getattr(request.state, "dashboard_operator", None)}

    @app.post("/api/system/pause")
    async def pause_system(request: Request):
        return {"operator": getattr(request.state, "dashboard_operator", None), "paused": True}

    return app


@pytest.fixture
def operator_env():
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


class TestDashboardSessionMiddleware:
    def test_health_is_public(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_public_namespace_is_public(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/public/ping")
        assert resp.status_code == 200
        assert resp.json() == {"public": True}

    def test_public_performance_namespace_is_public(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/public/performance/metrics")
        assert resp.status_code == 200
        assert resp.json() == {"public": True, "scope": "performance"}

    def test_public_portfolio_namespace_is_public(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/public/portfolio")
        assert resp.status_code == 200
        assert resp.json() == {"public": True, "scope": "portfolio"}

    def test_public_macro_namespace_is_public(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/public/macro/state")
        assert resp.status_code == 200
        assert resp.json() == {"public": True, "scope": "macro"}

    def test_protected_route_requires_login(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/private")
        assert resp.status_code == 401
        assert "Operator login required" in resp.json()["detail"]

    def test_auth_me_returns_unauthenticated_without_cookie(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_login_sets_cookie_and_unlocks_private_routes(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "super-secret-password"},
        )
        assert login_resp.status_code == 200
        assert SESSION_COOKIE_NAME in login_resp.cookies

        private_resp = client.get("/api/private")
        assert private_resp.status_code == 200
        assert private_resp.json()["operator"] == "operator"

        pause_resp = client.post("/api/system/pause")
        assert pause_resp.status_code == 200
        assert pause_resp.json()["paused"] is True

    def test_login_rejects_invalid_password(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        resp = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "wrong-password"},
        )
        assert resp.status_code == 401

    def test_logout_clears_session(self, operator_env):
        client = TestClient(_make_app(), base_url="http://localhost")
        client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "super-secret-password"},
        )

        logout_resp = client.post("/api/auth/logout")
        assert logout_resp.status_code == 200
        assert logout_resp.json()["authenticated"] is False

        private_resp = client.get("/api/private")
        assert private_resp.status_code == 401

    def test_login_requires_https_when_insecure_dev_disabled(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "operator",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
                "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
                "DASHBOARD_INSECURE_DEV_MODE": "false",
            },
            clear=False,
        ):
            client = TestClient(_make_app(), base_url="http://localhost")
            resp = client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "super-secret-password"},
            )
            assert resp.status_code == 403
            assert "requires HTTPS" in resp.json()["detail"]

    def test_https_login_works_when_dev_mode_disabled(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "operator",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
                "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
                "DASHBOARD_INSECURE_DEV_MODE": "false",
            },
            clear=False,
        ):
            client = TestClient(_make_app(), base_url="https://dashboard.example")
            resp = client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "super-secret-password"},
            )
            assert resp.status_code == 200
            assert SESSION_COOKIE_NAME in resp.cookies

    def test_forwarded_https_login_works_behind_proxy(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "operator",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
                "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
                "DASHBOARD_INSECURE_DEV_MODE": "false",
            },
            clear=False,
        ):
            client = TestClient(_make_app(), base_url="http://zeninvest.zenouz.ai")
            resp = client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "super-secret-password"},
                headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "zeninvest.zenouz.ai"},
            )
            assert resp.status_code == 200
            assert "Secure" in resp.headers["set-cookie"]

    def test_forwarded_https_allows_protected_route_after_login(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "operator",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
                "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
                "DASHBOARD_INSECURE_DEV_MODE": "false",
            },
            clear=False,
        ):
            client = TestClient(_make_app(), base_url="http://zeninvest.zenouz.ai")
            client.cookies.set(
                SESSION_COOKIE_NAME,
                create_session_token("operator"),
                domain="zeninvest.zenouz.ai",
                path="/",
            )

            private_resp = client.get(
                "/api/private",
                headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "zeninvest.zenouz.ai"},
            )
            assert private_resp.status_code == 200
            assert private_resp.json()["operator"] == "operator"


class TestDashboardAuthConfig:
    def test_missing_config_fails_closed(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": "",
                "DASHBOARD_SESSION_SECRET": "",
            },
            clear=False,
        ):
            with pytest.raises(RuntimeError):
                require_dashboard_auth_config()

    def test_invalid_hash_format_fails_closed(self):
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OPERATOR_USERNAME": "operator",
                "DASHBOARD_OPERATOR_PASSWORD_HASH": "not-a-valid-hash",
                "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
            },
            clear=False,
        ):
            with pytest.raises(RuntimeError):
                require_dashboard_auth_config()
