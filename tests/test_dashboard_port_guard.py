"""Dashboard proxy and access behavior tests."""


from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.backend.app.main import app

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist"


def test_dashboard_health_serves_on_localhost_port_8000():
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_health_serves_on_noncanonical_local_port():
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_health_head_serves_successfully():
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    response = client.head("/health")

    assert response.status_code == 200


@pytest.mark.skipif(
    not (_FRONTEND_DIST / "index.html").exists(),
    reason="frontend dist not built; run 'npm run build' in dashboard/frontend",
)
def test_dashboard_spa_route_uses_fallback_without_port_guard():
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
