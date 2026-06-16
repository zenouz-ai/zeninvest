"""Unit tests for frontend static serving helpers."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.backend.app.main import app
from dashboard.backend.app.static_frontend import should_spa_fallback

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/dashboard", True),
        ("/learning", True),
        ("/roadmap", True),
        ("/", True),
        ("/api/runs", False),
        ("/health", False),
        ("/assets/index-abc123.js", False),
        ("/assets/missing-chunk.js", False),
        ("/favicon.svg", False),
        ("/logo.svg", False),
        ("/assets/index-abc123.js.map", False),
    ],
)
def test_should_spa_fallback(path: str, expected: bool) -> None:
    assert should_spa_fallback(path) is expected


@pytest.mark.skipif(
    not (_FRONTEND_DIST / "index.html").exists(),
    reason="frontend dist not built; run 'npm run build' in dashboard/frontend",
)
def test_missing_asset_returns_404_not_html() -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    response = client.get("/assets/stale-chunk-that-does-not-exist.js")

    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


@pytest.mark.skipif(
    not (_FRONTEND_DIST / "index.html").exists(),
    reason="frontend dist not built; run 'npm run build' in dashboard/frontend",
)
def test_index_html_is_not_long_cached() -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache"


@pytest.mark.skipif(
    not (_FRONTEND_DIST / "index.html").exists(),
    reason="frontend dist not built; run 'npm run build' in dashboard/frontend",
)
def test_hashed_asset_is_immutable_cached() -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assets_dir = _FRONTEND_DIST / "assets"
    js_files = sorted(assets_dir.glob("index-*.js"))
    if not js_files:
        pytest.skip("no built index bundle in dist/assets")

    response = client.get(f"/assets/{js_files[0].name}")

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=31536000, immutable"
