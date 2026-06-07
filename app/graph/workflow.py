from functools import partial
from langgraph.graph import StateGraph, END
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.graph.state import GraphState
from app.graph.nodes import llm_node, validate_node, format_node, persist_node
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Routing functions ────────────────────────────────────────────────────────
# These are pure functions that read the state and return the name
# of the next node to execute. LangGraph calls them at each conditional edge.

def route_after_llm(state: GraphState) -> str:
    """
    After llm_node:
      - If error → END (return error to caller)
      - Otherwise → validate
    """
    if state.get("error"):
        return END
    return "validate"


def route_after_validate(state: GraphState) -> str:
    """
    After validate_node:
      - If error → END
      - If should_retry → llm (retry the LLM call)
      - Otherwise → format
    """
    if state.get("error"):
        return END
    if state.get("should_retry", False):
        return "llm"
    return "format"


def route_after_format(state: GraphState) -> str:
    """
    After format_node:
      - If error → END
      - Otherwise → persist
    """
    if state.get("error"):
        return END
    return "persist"


# ── Graph factory ─────────────────────────────────────────────────────────────

def build_graph(db: AsyncIOMotorDatabase = None):
    """
    Builds and compiles the LangGraph workflow.

    Called once at app startup and reused across all requests.
    The db handle is injected via partial so nodes can access
    MongoDB without being FastAPI-aware.

    Returns a compiled graph ready for .ainvoke()
    """

    # Inject db into persist_node via partial application.
    # This keeps nodes pure Python — no FastAPI imports in graph/nodes.py
    persist_with_db = partial(persist_node, db=db)

    # ── Build the graph ───────────────────────────────────────────────────────
    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("llm", llm_node)
    builder.add_node("validate", validate_node)
    builder.add_node("format", format_node)
    builder.add_node("persist", persist_with_db)

    # Set the entry point
    builder.set_entry_point("llm")

    # Add conditional edges (routing)
    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {
            "validate": "validate",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "llm": "llm",       # retry path
            "format": "format",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "format",
        route_after_format,
        {
            "persist": "persist",
            END: END,
        },
    )

    # persist always goes to END
    builder.add_edge("persist", END)

    # Compile — this validates the graph structure and returns
    # an executable object with .ainvoke() and .invoke()
    compiled = builder.compile()

    logger.info("langgraph_workflow_compiled")
    return compiled


# ── Module-level singleton ────────────────────────────────────────────────────
# The compiled graph is stored here after app startup calls init_workflow()
_workflow = None


def init_workflow(db: AsyncIOMotorDatabase) -> None:
    """Called once in app startup with the live DB handle."""
    global _workflow
    _workflow = build_graph(db=db)
    logger.info("workflow_initialised")


def get_workflow():
    """Returns the compiled workflow. Raises if not yet initialised."""
    if _workflow is None:
        raise RuntimeError(
            "Workflow not initialised. "
            "Call init_workflow() during app startup."
        )
    return _workflow