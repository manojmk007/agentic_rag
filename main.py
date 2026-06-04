"""
main.py
=========
FastAPI application entry point — Enterprise Cognitive Orchestrator.

Handles:
  - App creation with metadata and CORS
  - Lifespan events (startup: init MongoDB, models; shutdown: close)
  - Router registration
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from orchestrator.api.routes import router
from orchestrator.config.settings import settings
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.observability import (
    configure_logging,
    get_logger,
    set_request_id,
)

# Configure logging before everything else
configure_logging()
logger = get_logger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Startup: initialise MongoDB, preload embedding model.
    Shutdown: gracefully close all connections.
    """
    logger.info("orchestrator_startup", version="1.0.0", port=settings.app_port)

    # 1. MongoDB
    try:
        await mongodb_service.initialize()
        logger.info("mongodb_ready", database=settings.mongodb_database)
    except Exception as e:
        logger.error("mongodb_init_failed", error=str(e))
        raise

    # 2. Preload embedding model
    try:
        from orchestrator.services.embedder_service import embedder_service
        await embedder_service._ensure_model()
        logger.info("embedding_model_ready", model=settings.embedding_model)
    except Exception as e:
        logger.warning("embedding_preload_failed", error=str(e))

    logger.info("orchestrator_ready")
    yield

    # Shutdown
    logger.info("orchestrator_shutdown")
    await mongodb_service.close()
    logger.info("connections_closed")


# ── App Instance ─────────────────────────────────────────────

app = FastAPI(
    title="Enterprise Cognitive Orchestrator",
    description=(
        "Production-grade AI Assistant Decision Engine.\n\n"
        "**The orchestrator does NOT answer questions.**\n\n"
        "It analyzes queries, manages conversation state, selects retrieval "
        "strategies, validates evidence quality, and produces structured "
        "context packages for downstream Answer Generation Systems.\n\n"
        "**10-Step Pipeline:**\n"
        "1. Query Understanding\n"
        "2. Conversation Intelligence\n"
        "3. Route Scoring\n"
        "4. Retrieval Budget Management\n"
        "5. Query Optimization\n"
        "6. Context Quality Evaluation\n"
        "7. Self-Correction\n"
        "8. Context Assembly\n"
        "9. Risk Control\n"
        "10. Final Output\n"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inject a unique X-Request-Id header into every request."""
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        set_request_id(rid)
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


app.add_middleware(RequestIdMiddleware)

# ── Routes ────────────────────────────────────────────────────

app.include_router(router, tags=["Orchestrator"])


# ── Direct Run ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
