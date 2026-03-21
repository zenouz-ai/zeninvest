"""Tests for dashboard API key authentication middleware (US-7.1).

Uses FastAPI's TestClient so no real server is needed.
The middleware is tested in isolation via a minimal app fixture as well as
against the full dashboard app.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.middleware.auth import (
    APIKeyMiddleware,
    SAFE_PUBLIC_PREFIXES,
    _ALWAYS_PRIVATE_PREFIXES,
    _api_keys_match,
    get_api_key,
    warn_if_unauthenticated,
)


# ---------------------------------------------------------------------------
# Minimal app fixture — tests middleware logic without the full dashboard stack
# ---------------------------------------------------------------------------

def _make_app(
    api_key: str | None,
    public_prefixes: tuple[str, ...] = (),
) -> FastAPI:
    """Return a tiny FastAPI app with the auth middleware and a few test routes."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, api_key=api_key, public_prefixes=public_prefixes)

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

    # Routes that mirror real dashboard endpoints used in public-route tests.
    @app.get("/api/costs/daily")
    async def costs_daily():
        return []

    @app.get("/api/runs/")
    async def runs_list():
        return []

    @app.post("/api/runs/trigger-live")
    async def trigger_live_write():
        return {"triggered": True}

    @app.post("/api/system/pause")
    async def system_pause():
        return {"paused": True}

    @app.get("/api/portfolio/")
    async def portfolio():
        return {}

    @app.get("/api/opportunity/queue/")
    async def opportunity_queue():
        return []

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

    def test_api_keys_match_helper(self):
        assert _api_keys_match(_TEST_KEY, _TEST_KEY)
        assert not _api_keys_match("wrong", _TEST_KEY)
        assert not _api_keys_match("", _TEST_KEY)
        assert not _api_keys_match(_TEST_KEY, _TEST_KEY + "x")

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


# ---------------------------------------------------------------------------
# Tests: SSE stream + middleware (events router, real generator + DB)
# ---------------------------------------------------------------------------


class TestEventsStreamAuth:
    """GET /api/events/stream is protected like any other /api/* route."""

    def setup_method(self):
        import dashboard.backend.app.routers.events as events_mod

        self._settings_patch = patch.object(
            events_mod,
            "settings",
            SimpleNamespace(dashboard_enabled=True, dashboard_events_enabled=True),
        )
        self._settings_patch.start()

        from fastapi import FastAPI

        self.app = FastAPI()
        self.app.add_middleware(APIKeyMiddleware, api_key=_TEST_KEY, public_prefixes=())
        self.app.include_router(events_mod.router, prefix="/api/events", tags=["events"])
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        self._settings_patch.stop()

    def test_stream_forbidden_without_key(self):
        resp = self.client.get("/api/events/stream")
        assert resp.status_code == 403

    def test_stream_ok_with_key_first_chunk(self):
        with self.client.stream(
            "GET",
            "/api/events/stream",
            headers={"X-API-Key": _TEST_KEY},
        ) as resp:
            assert resp.status_code == 200
            ctype = resp.headers.get("content-type", "")
            assert "text/event-stream" in ctype
            buf = b""
            for chunk in resp.iter_bytes(chunk_size=512):
                buf += chunk
                if len(buf) >= 30:
                    break
            assert b"data:" in buf


# ---------------------------------------------------------------------------
# Tests: public demo routes (operator-configured, GET-only bypass)
# ---------------------------------------------------------------------------

_DEMO_PREFIXES = ("/api/costs/", "/api/runs/")


class TestPublicDemoRoutes:
    """When public_prefixes is set, GET requests to those prefixes bypass auth."""

    def setup_method(self):
        self.client = TestClient(
            _make_app(api_key=_TEST_KEY, public_prefixes=_DEMO_PREFIXES)
        )

    # --- Configured public prefix: GET allowed without key ---

    def test_public_get_allowed_without_key(self):
        resp = self.client.get("/api/costs/daily")
        assert resp.status_code == 200

    def test_public_runs_list_allowed_without_key(self):
        resp = self.client.get("/api/runs/")
        assert resp.status_code == 200

    def test_public_get_also_allowed_with_correct_key(self):
        resp = self.client.get("/api/costs/daily", headers={"X-API-Key": _TEST_KEY})
        assert resp.status_code == 200

    # --- POST to same prefix still requires key (write endpoint protection) ---

    def test_post_to_public_prefix_blocked_without_key(self):
        """POST /api/runs/trigger-live must be protected even if /api/runs/ is public."""
        resp = self.client.post("/api/runs/trigger-live")
        assert resp.status_code == 403

    def test_post_to_public_prefix_allowed_with_key(self):
        resp = self.client.post("/api/runs/trigger-live", headers={"X-API-Key": _TEST_KEY})
        assert resp.status_code == 200

    # --- Routes NOT in public_prefixes still require key ---

    def test_non_public_api_route_blocked(self):
        resp = self.client.get("/api/data")
        assert resp.status_code == 403

    def test_portfolio_not_public_blocked(self):
        resp = self.client.get("/api/portfolio/")
        assert resp.status_code == 403

    def test_opportunity_not_public_blocked(self):
        resp = self.client.get("/api/opportunity/queue/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: always-private prefix guard
# ---------------------------------------------------------------------------

class TestAlwaysPrivateGuard:
    """_ALWAYS_PRIVATE_PREFIXES cannot be bypassed even if listed in public_prefixes."""

    def test_system_prefix_always_blocked(self):
        """Attempting to make /api/system/ public is silently ignored."""
        client = TestClient(
            _make_app(api_key=_TEST_KEY, public_prefixes=("/api/system/",))
        )
        resp = client.post("/api/system/pause")
        assert resp.status_code == 403

    def test_trigger_prefix_always_blocked(self):
        client = TestClient(
            _make_app(api_key=_TEST_KEY, public_prefixes=("/api/runs/trigger",))
        )
        resp = client.post("/api/runs/trigger-live")
        assert resp.status_code == 403

    def test_safe_public_prefixes_constant_does_not_include_private(self):
        """SAFE_PUBLIC_PREFIXES must not contain any always-private prefix."""
        for safe in SAFE_PUBLIC_PREFIXES:
            for priv in _ALWAYS_PRIVATE_PREFIXES:
                assert not safe.startswith(priv), (
                    f"SAFE_PUBLIC_PREFIXES contains {safe!r} which starts with "
                    f"always-private prefix {priv!r}"
                )

    def test_mixed_config_private_filtered_out(self, caplog):
        """A config mixing safe and always-private prefixes logs a warning and filters."""
        import logging
        with caplog.at_level(logging.WARNING, logger="dashboard.backend.app.middleware.auth"):
            middleware_app = _make_app(
                api_key=_TEST_KEY,
                public_prefixes=("/api/costs/", "/api/system/"),
            )
        client = TestClient(middleware_app)
        # /api/costs/ GET is public
        assert client.get("/api/costs/daily").status_code == 200
        # /api/system/ POST is still blocked
        assert client.post("/api/system/pause").status_code == 403
        # Warning was logged
        assert any("always" in r.message.lower() or "protected" in r.message.lower()
                   for r in caplog.records)
