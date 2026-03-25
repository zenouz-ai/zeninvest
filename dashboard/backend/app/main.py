"""FastAPI application for dashboard backend."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send

from src.utils.config import get_settings

from .database import init_dashboard_tables
from .middleware.auth import DashboardSessionMiddleware
from .routers import (
    auth,
    api_usage,
    chat,
    commands,
    costs,
    dashboard,
    decisions,
    docs,
    events,
    evolution,
    macro,
    moderation,
    opportunity,
    orders,
    outcomes,
    performance,
    portfolio,
    public,
    research,
    risk,
    runs,
    status,
    stop_loss,
    system,
    universe,
)
from .services.auth import require_dashboard_auth_config

settings = get_settings()
_CANONICAL_DASHBOARD_PORT = settings.dashboard_canonical_port
_PORT_GUARD_BYPASS = (
    os.environ.get("DASHBOARD_DISABLE_PORT_GUARD", "false").strip().lower()
    in {"1", "true", "yes", "y", "on"}
)

# Path to built frontend (set at runtime; default for Docker)
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup/shutdown."""
    # Startup: Initialize dashboard tables
    if settings.dashboard_enabled:
        require_dashboard_auth_config()
        init_dashboard_tables()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Investment Agent Dashboard API",
    description="REST API and SSE stream for investment agent dashboard",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _request_port(request: Request) -> int | None:
    """Return the request port using Host first, then Starlette URL parsing."""
    host = request.headers.get("host", "").strip()
    if host:
        if host.startswith("[") and "]:" in host:
            _, _, port = host.rpartition(":")
            try:
                return int(port)
            except (TypeError, ValueError):
                return None
        if ":" in host:
            _, _, port = host.rpartition(":")
            try:
                return int(port)
            except (TypeError, ValueError):
                return None
    return request.url.port


def _port_from_host_value(host: str) -> int | None:
    host = host.strip()
    if not host:
        return None
    if host.startswith("[") and "]:" in host:
        _, _, port = host.rpartition(":")
    elif ":" in host:
        _, _, port = host.rpartition(":")
    else:
        return None
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def _scope_port(scope: Scope) -> int | None:
    headers = Headers(scope=scope)
    host = headers.get("host", "")
    port = _port_from_host_value(host)
    if port is not None:
        return port
    server = scope.get("server")
    if isinstance(server, tuple) and len(server) >= 2:
        try:
            return int(server[1])
        except (TypeError, ValueError):
            return None
    return None


class CanonicalPortStaticFiles(StaticFiles):
    """Static frontend that refuses requests on non-canonical ports."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_port = _scope_port(scope)
        if (
            not _PORT_GUARD_BYPASS
            and _CANONICAL_DASHBOARD_PORT is not None
            and request_port is not None
            and request_port != _CANONICAL_DASHBOARD_PORT
        ):
            response = JSONResponse(
                status_code=404,
                content={
                    "detail": (
                        f"Dashboard is only served on port {_CANONICAL_DASHBOARD_PORT}."
                    )
                },
            )
            await response(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


@app.middleware("http")
async def canonical_port_middleware(request: Request, call_next):
    """Serve the dashboard only on the configured canonical port.

    This prevents accidentally exposing a second copy of the same app on an
    ad-hoc local port such as 8001.
    """
    request_port = _request_port(request)
    if (
        not _PORT_GUARD_BYPASS
        and _CANONICAL_DASHBOARD_PORT is not None
        and request_port is not None
        and request_port != _CANONICAL_DASHBOARD_PORT
    ):
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"Dashboard is only served on port {_CANONICAL_DASHBOARD_PORT}."
                )
            },
        )
    return await call_next(request)

# CORS middleware for frontend — restrict to same-origin and VPS IP
_settings = get_settings()
_cors_origins = _settings.dashboard_cors_origins or [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session auth — public APIs live under /api/public/* and /api/auth/*.
app.add_middleware(DashboardSessionMiddleware)

# Register routers (must be before static mount so /api/* takes precedence)
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(public.router, prefix="/api/public", tags=["public"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(status.router, prefix="/api/status", tags=["status"])
app.include_router(universe.router, prefix="/api/universe", tags=["universe"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(decisions.router, prefix="/api/decisions", tags=["decisions"])
app.include_router(moderation.router, prefix="/api/moderation", tags=["moderation"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(opportunity.router, prefix="/api/opportunity", tags=["opportunity"])
app.include_router(outcomes.router, prefix="/api/outcomes", tags=["outcomes"])
app.include_router(stop_loss.router, prefix="/api/stop-loss", tags=["stop-loss"])
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(costs.router, prefix="/api/costs", tags=["costs"])
app.include_router(api_usage.router, prefix="/api/api-usage", tags=["api-usage"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(docs.router, prefix="/api/docs", tags=["docs"])
app.include_router(macro.router, prefix="/api/macro", tags=["macro"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(commands.router, prefix="/api/commands", tags=["commands"])
app.include_router(evolution.router, prefix="/api/evolution", tags=["evolution"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# Serve built frontend (SPA fallback for client-side routing)
if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        CanonicalPortStaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )

    @app.middleware("http")
    async def spa_fallback_middleware(request: Request, call_next):
        """Serve index.html for non-API 404s so client-side routing works."""
        response = await call_next(request)
        request_port = _request_port(request)
        if (
            response.status_code == 404
            and (
                _PORT_GUARD_BYPASS
                or _CANONICAL_DASHBOARD_PORT is None
                or request_port is None
                or request_port == _CANONICAL_DASHBOARD_PORT
            )
            and not request.url.path.startswith("/api")
            and request.url.path != "/health"
        ):
            index_path = _FRONTEND_DIST / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
        return response
else:
    # Fallback when dist not present (e.g. dev without build)
    @app.get("/")
    async def root():
        return {"message": "Investment Agent Dashboard API", "version": "1.0.0"}
