from app.graph.state import GraphState
from app.core.llm_service import generate_response
from app.core.validator import validate_response
from app.core.formatter import format_response
from app.models.response import LLMResponse
from app.utils.logger import get_logger
from app.utils.exceptions import (
    LLMServiceError,
    FormatterError,
    DatabaseError,
)

logger = get_logger(__name__)

# Maximum times we allow the graph to retry a low-confidence response
MAX_RETRIES = 1


async def llm_node(state: GraphState) -> dict:
    """
    Node 1 — Calls the LLM and stores the raw response in state.

    On failure: sets error and returns immediately.
    The graph router will skip remaining nodes if error is set.
    """
    logger.info(
        "graph_node_start",
        node="llm_node",
        session_id=state.get("session_id"),
        retry_count=state.get("retry_count", 0),
    )

    try:
        context = state["context"]
        llm_response = await generate_response(context)

        return {
            "llm_response": llm_response,
            "response_id": llm_response.response_id,
            "error": None,
        }

    except LLMServiceError as e:
        logger.error("llm_node_failed", error=str(e))
        return {
            "error": str(e),
            "error_node": "llm_node",
        }

    except Exception as e:
        logger.error("llm_node_unexpected_error", error=str(e))
        return {
            "error": f"Unexpected error in LLM node: {e}",
            "error_node": "llm_node",
        }


async def validate_node(state: GraphState) -> dict:
    """
    Node 2 — Validates the LLM response and decides whether to retry.

    Routing logic:
      - If validation passes → proceed to format_node
      - If validation fails AND retry_count < MAX_RETRIES → set should_retry=True
        (the graph router will send flow back to llm_node)
      - If validation fails AND retries exhausted → proceed anyway with
        validation_passed=False so the formatter adds a warning banner
    """
    logger.info("graph_node_start", node="validate_node")

    if state.get("error"):
        logger.warning("validate_node_skipped_due_to_error")
        return {}

    try:
        llm_response = state["llm_response"]
        context = state["context"]
        validation = validate_response(llm_response, context)

        retry_count = state.get("retry_count", 0)
        should_retry = False

        if not validation.passed and retry_count < MAX_RETRIES:
            logger.warning(
                "validation_failed_will_retry",
                response_id=llm_response.response_id,
                retry_count=retry_count,
                failure_reasons=validation.failure_reasons,
            )
            should_retry = True

        return {
            "validation": validation,
            "should_retry": should_retry,
            "retry_count": retry_count + (1 if should_retry else 0),
        }

    except Exception as e:
        logger.error("validate_node_failed", error=str(e))
        return {
            "error": f"Validation node error: {e}",
            "error_node": "validate_node",
        }


async def format_node(state: GraphState) -> dict:
    """
    Node 3 — Formats the validated response for the client.

    Always runs even if validation failed (so we can show the warning banner).
    Only skips if there was a hard error upstream.
    """
    logger.info("graph_node_start", node="format_node")

    if state.get("error"):
        logger.warning("format_node_skipped_due_to_error")
        return {}

    try:
        llm_response = state["llm_response"]
        validation = state["validation"]
        context = state["context"]

        formatted = format_response(llm_response, validation, context)

        return {"formatted": formatted}

    except FormatterError as e:
        logger.error("format_node_failed", error=str(e))
        return {
            "error": str(e),
            "error_node": "format_node",
        }

    except Exception as e:
        logger.error("format_node_unexpected_error", error=str(e))
        return {
            "error": f"Unexpected error in format node: {e}",
            "error_node": "format_node",
        }


async def persist_node(state: GraphState, db=None) -> dict:
    logger.info("graph_node_start", node="persist_node")

    if state.get("error") or not state.get("formatted"):
        logger.warning("persist_node_skipped")
        return {"persisted": False}

    if db is None:
        logger.warning("persist_node_no_db_injected")
        return {"persisted": False}

    try:
        from app.db.repositories.response_repo import ResponseRepository
        repo = ResponseRepository(db)

        # Inject user_query into metadata so correction engine can access it
        llm_response = state["llm_response"]
        llm_response.metadata["user_query"] = state["context"].user_query

        await repo.save_response(llm_response, state["formatted"])
        return {"persisted": True}

    except Exception as e:
        logger.error("persist_node_unexpected_error", error=str(e))
        return {"persisted": False}