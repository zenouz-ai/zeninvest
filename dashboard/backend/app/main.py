"""FastAPI application for dashboard backend."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    insights,
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

# CORS middleware for frontend — allow the canonical HTTPS domain plus local dev.
_settings = get_settings()
_cors_origins = _settings.dashboard_cors_origins or [
    "https://zeninvest.zenouz.ai",
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
app.include_router(insights.router, prefix="/api/insights", tags=["insights"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.head("/health")
async def health_head():
    """HEAD health check for reverse proxies and CLI probes."""
    return {"status": "ok"}


# Serve built frontend (SPA fallback for client-side routing)
if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )

    @app.middleware("http")
    async def spa_fallback_middleware(request: Request, call_next):
        """Serve index.html for non-API 404s so client-side routing works."""
        response = await call_next(request)
        if (
            response.status_code == 404
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
