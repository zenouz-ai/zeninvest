"""Dashboard app should only serve requests on the canonical local port."""

from fastapi.testclient import TestClient

from dashboard.backend.app.main import app


def test_dashboard_health_allowed_on_canonical_port():
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_health_rejected_on_non_canonical_port():
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    response = client.get("/health")

    assert response.status_code == 404
    assert "only served on port 8000" in response.json()["detail"]


def test_dashboard_spa_route_rejected_on_non_canonical_port():
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    response = client.get("/dashboard")

    assert response.status_code == 404
    assert "only served on port 8000" in response.json()["detail"]
