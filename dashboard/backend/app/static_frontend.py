"""Helpers for serving the built Vite SPA from FastAPI."""

from __future__ import annotations

from pathlib import Path

from starlette.responses import Response

_STATIC_PREFIXES = ("/assets/",)
_STATIC_EXTENSIONS = (
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".png",
    ".svg",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
)

INDEX_CACHE_CONTROL = "no-cache"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
BRAND_ASSET_CACHE_CONTROL = "public, max-age=86400"


def should_spa_fallback(path: str) -> bool:
    """Return True when a 404 should serve index.html for client-side routing."""
    if path.startswith("/api") or path == "/health":
        return False
    if any(path.startswith(prefix) for prefix in _STATIC_PREFIXES):
        return False
    if any(path.endswith(ext) for ext in _STATIC_EXTENSIONS):
        return False
    return True


def index_html_response(index_path: Path) -> Response:
    """Serve index.html with revalidation-friendly cache headers."""
    from fastapi.responses import FileResponse

    return FileResponse(index_path, headers={"Cache-Control": INDEX_CACHE_CONTROL})


def apply_frontend_cache_headers(path: str, response: Response) -> None:
    """Apply cache policy for built frontend responses."""
    if path == "/" or path == "/index.html" or (
        should_spa_fallback(path) and "text/html" in response.headers.get("content-type", "")
    ):
        response.headers["Cache-Control"] = INDEX_CACHE_CONTROL
    elif path.startswith("/assets/"):
        response.headers["Cache-Control"] = ASSET_CACHE_CONTROL
    elif path in ("/favicon.svg", "/logo.svg"):
        response.headers["Cache-Control"] = BRAND_ASSET_CACHE_CONTROL
