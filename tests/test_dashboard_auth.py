"""Tests for dashboard API key authentication middleware (US-7.1).

Uses FastAPI's TestClient so no real server is needed.
The middleware is tested in isolation via a minimal app fixture as well as
against the full dashboard app.
"""

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.middleware.auth import APIKeyMiddleware, get_api_key, warn_if_unauthenticated


# ---------------------------------------------------------------------------
# Minimal app fixture — tests middleware logic without the full dashboard stack
# ---------------------------------------------------------------------------

def _make_app(api_key: str | None) -> FastAPI:
    """Return a tiny FastAPI app with the auth middleware and a few test routes."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, api_key=api_key)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/data")
    async def data():
        return {"data": "secret"}

    @app.post("/api/runs/trigger-live")
    async def trigger_live():
        return {"triggered": True}

    @app.get("/docs")
    async def docs_stub():
        return {"docs": True}

    @app.get("/openapi.json")
    async def openapi_stub():
        return {}

    @app.get("/")
    async def spa_root():
        return {"app": "frontend"}

    return app


# ---------------------------------------------------------------------------
# Tests: no API key configured (dev / unauthenticated mode)
# ---------------------------------------------------------------------------

class TestNoKeyConfigured:
    """When DASHBOARD_API_KEY is not set all requests pass through."""

    def setup_method(self):
        self.client = TestClient(_make_app(api_key=None))

    def test_api_route_allowed_without_header(self):
        resp = self.client.get("/api/data")
        assert resp.status_code == 200

    def test_trigger_live_allowed_without_header(self):
        resp = self.client.post("/api/runs/trigger-live")
        assert resp.status_code == 200

    def test_health_allowed(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_frontend_route_allowed(self):
        resp = self.client.get("/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: API key configured
# ---------------------------------------------------------------------------

_TEST_KEY = "test-secret-key-abc123"


class TestKeyConfigured:
    """When DASHBOARD_API_KEY is set, /api/* requires matching X-API-Key header."""

    def setup_method(self):
        self.client = TestClient(_make_app(api_key=_TEST_KEY))

    # --- Public paths always pass ---

    def test_health_always_allowed(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_docs_always_allowed(self):
        resp = self.client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_always_allowed(self):
        resp = self.client.get("/openapi.json")
        assert resp.status_code == 200

    def test_spa_route_not_restricted(self):
        """Non-/api paths (SPA routes) are not behind auth."""
        resp = self.client.get("/")
        assert resp.status_code == 200

    # --- /api/* without header → 403 ---

    def test_api_route_blocked_without_header(self):
        resp = self.client.get("/api/data")
        assert resp.status_code == 403

    def test_trigger_live_blocked_without_header(self):
        """POST /api/runs/trigger-live must be protected."""
        resp = self.client.post("/api/runs/trigger-live")
        assert resp.status_code == 403

    def test_403_returns_json_detail(self):
        resp = self.client.get("/api/data")
        assert resp.status_code == 403
        body = resp.json()
        assert "detail" in body
        assert "X-API-Key" in body["detail"]

    # --- /api/* with wrong key → 403 ---

    def test_wrong_key_blocked(self):
        resp = self.client.get("/api/data", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403

    def test_empty_key_blocked(self):
        resp = self.client.get("/api/data", headers={"X-API-Key": ""})
        assert resp.status_code == 403

    # --- /api/* with correct key → 200 ---

    def test_correct_key_allowed(self):
        resp = self.client.get("/api/data", headers={"X-API-Key": _TEST_KEY})
        assert resp.status_code == 200

    def test_post_trigger_live_correct_key_allowed(self):
        resp = self.client.post("/api/runs/trigger-live", headers={"X-API-Key": _TEST_KEY})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: get_api_key() helper reads from environment
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHBOARD_API_KEY", None)
            assert get_api_key() is None

    def test_returns_key_when_set(self):
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "env-key-xyz"}):
            assert get_api_key() == "env-key-xyz"

    def test_returns_none_for_empty_string(self):
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}):
            assert get_api_key() is None


# ---------------------------------------------------------------------------
# Tests: warn_if_unauthenticated() logs warning when no key is set
# ---------------------------------------------------------------------------

class TestWarnIfUnauthenticated:
    def test_warns_when_no_key(self, caplog):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHBOARD_API_KEY", None)
            import logging
            with caplog.at_level(logging.WARNING, logger="dashboard.backend.app.middleware.auth"):
                warn_if_unauthenticated()
        assert any("DASHBOARD_API_KEY" in r.message for r in caplog.records)

    def test_no_warn_when_key_set(self, caplog):
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "some-key"}):
            import logging
            with caplog.at_level(logging.WARNING, logger="dashboard.backend.app.middleware.auth"):
                warn_if_unauthenticated()
        assert not any("DASHBOARD_API_KEY" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests: full dashboard app integration
# ---------------------------------------------------------------------------

class TestFullAppIntegration:
    """Smoke-test auth against the real dashboard app with mocked dependencies."""

    def setup_method(self):
        # Patch get_api_key so the real app uses our test key, and suppress
        # DB init + settings loading side-effects.
        self._key_patcher = patch(
            "dashboard.backend.app.middleware.auth.get_api_key",
            return_value=_TEST_KEY,
        )
        self._key_patcher.start()

        self._settings_patcher = patch(
            "dashboard.backend.app.main.settings",
        )
        mock_settings = self._settings_patcher.start()
        mock_settings.dashboard_enabled = False  # skip DB init in lifespan
        mock_settings.dashboard_cors_origins = None

        self._init_patcher = patch("dashboard.backend.app.main.init_dashboard_tables")
        self._init_patcher.start()

        from dashboard.backend.app.main import app
        # Re-add middleware with test key for this test (middleware is bound at import time,
        # so we test the real app routes via its existing middleware configuration).
        self.client = TestClient(app, raise_server_exceptions=False)

    def teardown_method(self):
        self._key_patcher.stop()
        self._settings_patcher.stop()
        self._init_patcher.stop()

    def test_health_always_accessible(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
