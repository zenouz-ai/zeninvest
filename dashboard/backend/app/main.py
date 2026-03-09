"""FastAPI application for dashboard backend."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.utils.config import get_settings

from .database import init_dashboard_tables
from .routers import events, orders, portfolio, runs, universe

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup/shutdown."""
    # Startup: Initialize dashboard tables
    if settings.dashboard_enabled:
        init_dashboard_tables()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Investment Agent Dashboard API",
    description="REST API and SSE stream for investment agent dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(universe.router, prefix="/api/universe", tags=["universe"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(events.router, prefix="/api/events", tags=["events"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Investment Agent Dashboard API", "version": "1.0.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
