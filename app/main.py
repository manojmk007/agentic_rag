from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.client import connect_to_mongodb, close_mongodb_connection
from app.utils.logger import setup_logging, get_logger
from app.utils.exceptions import (
    LLMServiceError,
    ValidationError,
    DatabaseError,
    ResponseNotFoundError,
)
from app.api.v1 import generate, feedback, mempalace

# Initialise logging before anything else
setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("app_starting", env=settings.app_env, model=settings.llm_model)
    await connect_to_mongodb()

    # Initialise the LangGraph workflow with the live DB handle
    from app.graph.workflow import init_workflow
    from app.db.client import get_database
    init_workflow(db=get_database())

    logger.info("app_ready")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("app_shutting_down")
    await close_mongodb_connection()
    logger.info("app_stopped")


# ── Create the FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title="LLM Feedback Service",
    description="LLM generation, response validation, formatting, and feedback loop for Memory-Aware Hybrid RAG",
    version="0.1.0",
    docs_url="/docs",          # Swagger UI at /docs
    redoc_url="/redoc",        # ReDoc at /redoc
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handlers ─────────────────────────────────────────────────
@app.exception_handler(LLMServiceError)
async def llm_error_handler(request: Request, exc: LLMServiceError):
    logger.error("llm_service_error", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=502,
        content={"error": "llm_unavailable", "detail": str(exc)},
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    logger.warning("validation_failed", error=str(exc), scores=exc.scores)
    return JSONResponse(
        status_code=422,
        content={"error": "validation_failed", "detail": str(exc), "scores": exc.scores},
    )


@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError):
    logger.error("database_error", error=str(exc), collection=exc.collection)
    return JSONResponse(
        status_code=503,
        content={"error": "database_unavailable", "detail": str(exc)},
    )


@app.exception_handler(ResponseNotFoundError)
async def not_found_handler(request: Request, exc: ResponseNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "detail": str(exc)},
    )


# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(generate.router, prefix="/v1", tags=["generation"])
app.include_router(feedback.router, prefix="/v1", tags=["feedback"])
app.include_router(mempalace.router, prefix="/v1", tags=["mempalace"])  # add this


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health_check():
    """
    Lightweight liveness probe.
    Kubernetes/Docker calls this every few seconds — keep it fast.
    """
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/ready", tags=["health"])
async def readiness_check():
    """
    Readiness probe — verifies the database connection is alive.
    Kubernetes only routes traffic here if this returns 200.
    """
    from app.db.client import get_database
    try:
        db = get_database()
        await db.command("ping")
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        logger.error("readiness_check_failed", error=str(e))
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "disconnected"},
        )