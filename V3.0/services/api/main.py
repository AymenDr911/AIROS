"""AIROS V3 backend API - FastAPI application factory (Slice 5, DEC-011)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import me


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AIROS V3 API",
        version="0.1.0",
        description="Resource server for the AIROS V3 product UI (DEC-011).",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(me.router)

    @app.get("/api/health")
    def health() -> dict:
        """Liveness probe (no auth) - also surfaces missing critical config."""
        return {
            "status": "ok",
            "service": "airos-api",
            "env": settings.env,
            "config": "ok" if not settings.missing_critical() else "incomplete",
        }

    return app


app = create_app()
