"""Dashboard proxy and access behavior tests."""

from fastapi.testclient import TestClient

from dashboard.backend.app.main import app


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


def test_dashboard_spa_route_uses_fallback_without_port_guard():
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
