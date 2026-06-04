"""
orchestrator/graph_state.py
=============================
LangGraph state definitions for the orchestrator pipeline.
"""

from typing import TypedDict, Optional, Any
from orchestrator.models.query_models import QueryAnalysis
from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.routing_models import RouteScores, RetrievalBudget
from orchestrator.models.context_models import ContextQuality, ContextPackage, RiskAssessment
from orchestrator.models.output_models import OrchestratorOutput
from orchestrator.steps.step5_query_optimizer import OptimizedQuery


class OrchestratorState(TypedDict):
    """
    The state dictionary that is passed sequentially through the LangGraph nodes.
    Each node receives the current state and returns a dict with fields to update.
    """
    # ── Initial Input ─────────────────────────
    query: str
    session_id: str
    tenant_id: Optional[str]
    filters: Optional[dict[str, Any]]
    
    # ── Orchestrator Internal State ───────────
    conversation_history: list[dict]
    query_analysis: Optional[QueryAnalysis]
    conversation_state: Optional[ConversationState]
    route_scores: Optional[RouteScores]
    budget: Optional[RetrievalBudget]
    
    # Retrieval & Correction Loop State
    optimized_query: Optional[OptimizedQuery]
    memories: list[dict]
    retrieved_chunks: list[dict]
    quality: Optional[ContextQuality]
    retry_count: int
    needs_clarification: bool
    clarification_reason: str
    
    # ── Final Outputs ─────────────────────────
    context_package: Optional[ContextPackage]
    risk: Optional[RiskAssessment]
    output: Optional[OrchestratorOutput]
    step_timings: dict[str, float]
