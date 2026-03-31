"""
FastAPI application factory.

This is the entry point. It:
1. Creates the FastAPI app
2. Registers routes
3. Adds middleware (CORS, logging, etc.)
4. Sets up startup/shutdown events (DB init, etc.)

Why a factory function?
- Tests can create isolated app instances
- Different configs for dev/staging/prod
- No global app state
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medscribe.api.agent_routes import router as agent_router
from medscribe.api.auth_routes import router as auth_router
from medscribe.api.epj_routes import router as epj_router
from medscribe.api.routes import router
from medscribe.api.schemas import HealthResponse
from medscribe.api.ws import router as ws_router
from medscribe.config import get_settings
from medscribe.services.factory import get_llm_provider, get_stt_provider
from medscribe.storage.database import init_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()
    logger.info("app.starting", environment=settings.environment.value)

    # Create database tables
    await init_db()
    logger.info("app.database_initialized")

    yield  # App is running

    logger.info("app.shutting_down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description=(
            "Modular AI microservice platform for clinical documentation. "
            "Provides speech-to-text, LLM-powered structuring, and workflow "
            "orchestration with full audit trails."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — restrict in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(auth_router)  # Auth (unprotected — generates tokens)
    app.include_router(router)       # Main API (protected by JWT)
    app.include_router(ws_router)    # WebSocket (streaming transcription)
    app.include_router(agent_router) # Agentic AI workflows
    app.include_router(epj_router)   # EPJ bridge

    # Lightweight liveness check — always responds, never loads models
    @app.get("/healthz")
    async def liveness():
        """Liveness probe — confirms the API process is running."""
        return {"status": "alive"}

    # Full health check — tests AI service connectivity
    @app.get("/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        """Full health check including AI services. May be slow on first call."""
        services = {}
        try:
            llm = get_llm_provider()
            services["llm"] = await llm.health_check()
        except Exception:
            services["llm"] = False

        try:
            stt = get_stt_provider()
            services["stt"] = await stt.health_check()
        except Exception:
            services["stt"] = False

        overall = "healthy" if all(services.values()) else "degraded"
        return HealthResponse(
            status=overall,
            version=settings.api_version,
            services=services,
        )

    return app
