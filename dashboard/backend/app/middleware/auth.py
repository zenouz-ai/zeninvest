"""Session-based dashboard auth middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..services.auth import current_operator_session, operator_transport_allowed

# Public exact paths, independent of operator login.
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
})

# Public API namespaces.
_PUBLIC_API_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/public/",
)


class DashboardSessionMiddleware(BaseHTTPMiddleware):
    """Protect all non-public dashboard API routes with an operator session."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in _PUBLIC_PATHS:
            return await call_next(request)

        if not path.startswith("/api/"):
            return await call_next(request)

        if any(path.startswith(prefix) for prefix in _PUBLIC_API_PREFIXES):
            return await call_next(request)

        session = current_operator_session(request)
        if session is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Operator login required."},
            )

        if not operator_transport_allowed(request):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Operator access requires HTTPS. For local development, use "
                        "localhost with DASHBOARD_INSECURE_DEV_MODE=true."
                    ),
                },
            )

        request.state.dashboard_operator = session.username
        return await call_next(request)
