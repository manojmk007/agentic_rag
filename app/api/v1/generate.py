import time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.dependencies import get_db
from app.models.context import AssembledContext
from app.models.response import FormattedResponse
from app.graph.workflow import get_workflow
from app.graph.state import GraphState
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/generate", response_model=FormattedResponse, status_code=200)
async def generate(
    context: AssembledContext,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Main generation endpoint.

    Accepts an AssembledContext from the upstream Context Assembly team,
    runs the full LangGraph pipeline:
      LLM → Validate → Format → Persist

    Returns a FormattedResponse with:
      - Formatted answer with inline citations
      - Confidence score and validation status
      - Source metadata for the sources panel
      - response_id for tracking feedback

    The response_id in the return value is what the client must send
    back when submitting feedback via POST /v1/feedback.
    """
    request_start = time.monotonic()

    logger.info(
        "generate_request_received",
        session_id=context.session_id,
        tenant_id=context.tenant_id,
        num_sources=len(context.source_documents),
        has_memory=bool(context.memory_context),
        has_fresh_context=bool(context.fresh_context),
    )

    # Build the initial graph state
    initial_state: GraphState = {
        "context": context,
        "session_id": context.session_id,
        "tenant_id": context.tenant_id,
        "llm_response": None,
        "validation": None,
        "formatted": None,
        "persisted": False,
        "response_id": "",
        "error": None,
        "error_node": None,
        "should_retry": False,
        "retry_count": 0,
    }

    # Run the graph
    try:
        workflow = get_workflow()
        final_state: GraphState = await workflow.ainvoke(initial_state)
    except Exception as e:
        logger.error(
            "workflow_invoke_failed",
            session_id=context.session_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {e}",
        )

    # Check if any node set an error
    if final_state.get("error"):
        error_node = final_state.get("error_node", "unknown")
        error_msg = final_state.get("error")
        logger.error(
            "workflow_completed_with_error",
            error_node=error_node,
            error=error_msg,
            session_id=context.session_id,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "pipeline_error",
                "node": error_node,
                "detail": error_msg,
            },
        )

    # Verify we got a formatted response
    formatted = final_state.get("formatted")
    if formatted is None:
        logger.error(
            "workflow_produced_no_output",
            session_id=context.session_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Pipeline completed but produced no formatted response.",
        )

    total_latency = round((time.monotonic() - request_start) * 1000, 2)

    logger.info(
        "generate_request_completed",
        response_id=formatted.response_id,
        session_id=context.session_id,
        validation_passed=formatted.validation_passed,
        confidence=formatted.confidence_score,
        persisted=final_state.get("persisted", False),
        total_latency_ms=total_latency,
    )

    return formatted


@router.get("/generate/{response_id}")
async def get_generated_response(
    response_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Retrieve a previously generated response by its ID.
    Useful for the client to re-fetch a response without regenerating.
    """
    from app.db.repositories.response_repo import ResponseRepository
    repo = ResponseRepository(db)
    doc = await repo.get_response(response_id)

    return {
        "response_id": doc["response_id"],
        "session_id": doc["session_id"],
        "answer": doc["formatted_answer"],
        "confidence_score": doc["confidence_score"],
        "validation_passed": doc["validation_passed"],
        "source_ids": doc["source_ids"],
        "sources": doc["sources"],
        "model_used": doc["model_used"],
        "latency_ms": doc["latency_ms"],
        "created_at": doc["created_at"],
    }

