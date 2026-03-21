"""API key authentication middleware for the dashboard backend.

All /api/* routes require a valid X-API-Key header when DASHBOARD_API_KEY is set
in the environment. Two exemption mechanisms:

1. ``_PUBLIC_PATHS`` — exact-match paths that bypass auth entirely regardless of
   method (health, docs, openapi).
2. ``public_prefixes`` — operator-configurable prefix list for demo/read-only
   exposure. Only GET requests to matching /api/* paths are exempted; all other
   methods (POST, DELETE, PATCH) still require the key, so write endpoints such
   as ``POST /api/runs/trigger-live`` and ``POST /api/system/force-sell`` remain
   protected even when the path prefix is listed as public.

When DASHBOARD_API_KEY is not set the middleware allows all requests through with
a startup warning — this preserves backward-compatible local development behaviour.
"""

import hmac
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

# Safe read-only prefixes that can be added to public_prefixes in settings.yaml.
# Documented here so operators know which choices exist.
SAFE_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/docs/",       # Roadmap & architecture content
    "/api/costs/",      # API spend — no strategy data
    "/api/runs/",       # Cycle history — timestamps + status counts
    "/api/performance/metrics",  # Aggregate Sharpe/win-rate
)

# Prefixes that should NEVER be made public regardless of config.
# The middleware enforces this as a hard guard.
_ALWAYS_PRIVATE_PREFIXES: tuple[str, ...] = (
    "/api/system/",      # pause, resume, force-sell, trigger-live
    "/api/runs/trigger", # live + dry-run cycle triggers
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce X-API-Key authentication on all /api/* endpoints.

    Behaviour:
    - If DASHBOARD_API_KEY env var is not set: middleware is a no-op (all requests
      pass through). A warning is logged at startup via ``warn_if_unauthenticated()``.
    - If DASHBOARD_API_KEY is set: every request to /api/* must supply a matching
      ``X-API-Key`` header; missing or wrong key → 403.
    - ``public_prefixes``: GET requests whose path starts with one of these prefixes
      bypass auth. POST/DELETE/PATCH to the same prefixes still require the key.
      Paths in ``_ALWAYS_PRIVATE_PREFIXES`` are never exempted regardless of config.
    - Exact public paths (/health, /docs, /openapi.json, /redoc) are always allowed.
    - All other paths (frontend static assets, SPA routes) are also allowed — auth
      only guards the API surface.
    """

    def __init__(
        self,
        app,
        api_key: str | None,
        public_prefixes: tuple[str, ...] | list[str] = (),
    ) -> None:
        super().__init__(app)
        self._api_key = api_key
        # Filter out any accidentally-configured always-private prefixes.
        filtered = [
            p for p in public_prefixes
            if not any(p.startswith(priv) for priv in _ALWAYS_PRIVATE_PREFIXES)
        ]
        if len(filtered) < len(list(public_prefixes)):
            dropped = set(public_prefixes) - set(filtered)
            logger.warning(
                "dashboard.public_routes: ignoring %s — these prefixes are always "
                "protected and cannot be made public: %s",
                dropped, list(_ALWAYS_PRIVATE_PREFIXES),
            )
        self._public_prefixes: tuple[str, ...] = tuple(filtered)

    def _is_public_demo_route(self, path: str, method: str) -> bool:
        """Return True when the request is a safe read-only demo route."""
        if method.upper() != "GET":
            return False
        # Hard block: always-private prefixes are never public.
        if any(path.startswith(priv) for priv in _ALWAYS_PRIVATE_PREFIXES):
            return False
        return any(path.startswith(prefix) for prefix in self._public_prefixes)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Always allow exact public paths.
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Only enforce on /api/* routes.
        if not path.startswith("/api/"):
            return await call_next(request)

        # No key configured → allow (dev / unauthenticated mode).
        if not self._api_key:
            return await call_next(request)

        # Allow configured public demo routes (GET only, never write endpoints).
        if self._is_public_demo_route(path, method):
            return await call_next(request)

        # Validate the supplied key (timing-safe compare when lengths match).
        supplied = request.headers.get("X-API-Key", "")
        expected = self._api_key or ""
        if not _api_keys_match(supplied, expected):
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid or missing API key. Supply X-API-Key header."},
            )

        return await call_next(request)


def _api_keys_match(supplied: str, expected: str) -> bool:
    """Constant-time comparison for UTF-8 API keys (avoids trivial timing leaks)."""
    try:
        sa = supplied.encode("utf-8")
        eb = expected.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if len(sa) != len(eb):
        return False
    return hmac.compare_digest(sa, eb)


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
