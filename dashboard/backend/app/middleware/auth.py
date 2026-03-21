"""API key authentication middleware for the dashboard backend.

All /api/* routes require a valid X-API-Key header when DASHBOARD_API_KEY is set
in the environment. Excluded paths (health, docs, openapi) remain unauthenticated.

When DASHBOARD_API_KEY is not set the middleware allows all requests through with
a startup warning — this preserves backward-compatible local development behaviour.
"""

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that are always public regardless of auth configuration.
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce X-API-Key authentication on all /api/* endpoints.

    Behaviour:
    - If DASHBOARD_API_KEY env var is not set: middleware is a no-op (all requests
      pass through). A warning is logged at startup via ``warn_if_unauthenticated()``.
    - If DASHBOARD_API_KEY is set: every request to /api/* must supply a matching
      ``X-API-Key`` header; missing or wrong key → 403.
    - Public paths (/health, /docs, /openapi.json, /redoc) are always allowed.
    - All other paths (frontend static assets, SPA routes) are also allowed — auth
      only guards the API surface.
    """

    def __init__(self, app, api_key: str | None) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow public paths.
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Only enforce on /api/* routes.
        if not path.startswith("/api/"):
            return await call_next(request)

        # No key configured → allow (dev / unauthenticated mode).
        if not self._api_key:
            return await call_next(request)

        # Validate the supplied key.
        supplied = request.headers.get("X-API-Key", "")
        if supplied != self._api_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid or missing API key. Supply X-API-Key header."},
            )

        return await call_next(request)


def get_api_key() -> str | None:
    """Return DASHBOARD_API_KEY from environment, or None if not set."""
    return os.environ.get("DASHBOARD_API_KEY") or None


def warn_if_unauthenticated() -> None:
    """Log a warning at startup when no API key is configured."""
    if not get_api_key():
        logger.warning(
            "DASHBOARD_API_KEY is not set — dashboard API endpoints are "
            "unauthenticated. Set DASHBOARD_API_KEY in .env before exposing "
            "the dashboard beyond localhost."
        )
