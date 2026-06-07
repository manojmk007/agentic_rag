from typing import TypedDict, Optional, Any
from app.models.context import AssembledContext
from app.models.response import LLMResponse, FormattedResponse
from app.models.validation import ValidationResult


class GraphState(TypedDict, total=False):
    """
    Shared state that flows through every node in the LangGraph workflow.

    total=False means every field is optional at the TypedDict level.
    In practice each node guarantees its output fields are set before
    the next node runs — enforced by node ordering in the graph.

    Field ownership:
      context         → set by the caller before graph.invoke()
      llm_response    → set by llm_node
      validation      → set by validate_node
      formatted       → set by format_node
      persisted       → set by persist_node
      error           → set by any node on failure
      should_retry    → set by validate_node when score is borderline
    """
    # Input — provided by the caller
    context: AssembledContext

    # LLM node output
    llm_response: Optional[LLMResponse]

    # Validation node output
    validation: Optional[ValidationResult]

    # Formatter node output
    formatted: Optional[FormattedResponse]

    # Persist node output
    persisted: bool
    response_id: str

    # Error handling
    error: Optional[str]
    error_node: Optional[str]

    # Routing signals
    should_retry: bool
    retry_count: int

    # Metadata carried through the whole graph
    tenant_id: str
    session_id: str