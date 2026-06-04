"""
orchestrator/api/routes.py
============================
FastAPI router for the Cognitive Orchestrator.

Endpoints:
  POST /orchestrate              — Run the full orchestration pipeline
  GET  /health                   — Service health check
  GET  /metrics                  — Orchestrator metrics
  GET  /conversations/{id}       — Get conversation history
  DELETE /conversations/{id}     — Clear a session
"""

import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional

from orchestrator.api.models import (
    OrchestrateRequest,
    HealthResponse,
    ConversationHistoryResponse,
)
from orchestrator.orchestrator import CognitiveOrchestrator
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.conversation_store import conversation_store
from orchestrator.services.memory_store import memory_store
from orchestrator.services.retrieval_interface import create_retriever
from orchestrator.services.mongodb_retriever import MongoDBRetriever
from orchestrator.services.document_ingestion import document_ingestion_service
from orchestrator.services.observability import get_logger, metrics, set_request_id

logger = get_logger(__name__)

router = APIRouter()

# Module-level orchestrator instance (initialized with MongoDBRetriever)
_orchestrator = CognitiveOrchestrator(retriever=MongoDBRetriever())


def get_orchestrator() -> CognitiveOrchestrator:
    """Return the module-level orchestrator singleton."""
    return _orchestrator



# ═══════════════════════════════════════════════════════════════
# POST /orchestrate
# ═══════════════════════════════════════════════════════════════

@router.post("/orchestrate", summary="Run Cognitive Orchestration Pipeline")
async def orchestrate_endpoint(request: OrchestrateRequest):
    """
    Main orchestration endpoint.

    Runs the full 10-step pipeline:
      Query Understanding → Conversation Intelligence → Route Scoring →
      Budget → Optimize → Retrieve → Evaluate → Self-Correct →
      Assemble → Risk Control → Output

    Returns structured JSON context package for downstream LLM.
    """
    request_id = str(uuid.uuid4())
    set_request_id(request_id)

    logger.info(
        "orchestrate_request",
        query=request.query[:80],
        session_id=request.session_id,
    )

    try:
        output = await _orchestrator.orchestrate(
            query=request.query,
            session_id=request.session_id,
            tenant_id=request.tenant_id,
            filters=request.filters,
        )
        return output.model_dump()
    except Exception as e:
        logger.error("orchestration_failed", error=str(e), request_id=request_id)
        raise HTTPException(
            status_code=500,
            detail=f"Orchestration failed: {str(e)}",
        )


# ═══════════════════════════════════════════════════════════════
# GET /health
# ═══════════════════════════════════════════════════════════════

@router.get("/health", response_model=HealthResponse, summary="Service Health Check")
async def health_check():
    """Check connectivity to all backend services."""
    mongo_ok = await mongodb_service.health_check()
    retriever_ok = await _orchestrator._retriever.health_check()

    services = {
        "mongodb": mongo_ok,
        "retriever": retriever_ok,
    }

    all_healthy = all(services.values())
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services,
    )


# ═══════════════════════════════════════════════════════════════
# GET /metrics
# ═══════════════════════════════════════════════════════════════

@router.get("/metrics", summary="Orchestrator Metrics")
async def get_metrics():
    """Return orchestrator performance metrics."""
    memory_stats = {}
    try:
        memory_stats = await memory_store.get_stats()
    except Exception:
        pass

    return {
        **metrics.summary(),
        "memory_store": memory_stats,
    }


# ═══════════════════════════════════════════════════════════════
# Conversation Management
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/conversations/{session_id}",
    response_model=ConversationHistoryResponse,
    summary="Get Conversation History",
)
async def get_conversation(session_id: str):
    """Retrieve conversation history for a session."""
    turns = await conversation_store.get_history(session_id)
    return ConversationHistoryResponse(
        session_id=session_id,
        turns=turns,
        turn_count=len(turns),
    )


@router.delete(
    "/conversations/{session_id}",
    summary="Clear Conversation Session",
)
async def clear_conversation(session_id: str):
    """Delete a conversation session."""
    success = await conversation_store.clear_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "success", "message": f"Session {session_id} cleared"}


# ═══════════════════════════════════════════════════════════════
# Document Ingestion & Management
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/documents/upload",
    summary="Upload and Ingest a Document",
)
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
):
    """
    Ingest a document into the RAG storage.
    Supports .txt, .docx, and .pdf formats.
    Chunks, embeds, and indexes document text.
    """
    try:
        content = await file.read()
        result = await document_ingestion_service.ingest_document(
            file_bytes=content,
            filename=file.filename,
            tenant_id=tenant_id,
            category=category,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("document_upload_failed", filename=file.filename, error=str(e))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.delete(
    "/documents/{doc_id}",
    summary="Delete Ingested Document",
)
async def delete_document(doc_id: str):
    """Delete all chunks associated with a document ID."""
    success = await document_ingestion_service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "message": f"Document {doc_id} deleted successfully"}

