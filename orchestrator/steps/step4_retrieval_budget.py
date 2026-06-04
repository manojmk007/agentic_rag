"""
orchestrator/steps/step4_retrieval_budget.py
==============================================
Step 4 — Retrieval Budget Manager.

Decision matrix:
  conversation_score > 0.90 → SKIP retrieval
  memory_score > 0.90       → LOW budget (memory only)
  Moderate scores (0.5–0.9) → MEDIUM budget
  All scores < 0.5          → HIGH budget

Budget levels control top_k and which retrieval sources to query.
"""

from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.routing_models import RouteScores, RetrievalBudget
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


@track_latency("step4_retrieval_budget")
async def allocate_budget(
    route_scores: RouteScores,
    query_analysis: QueryAnalysis,
) -> RetrievalBudget:
    """
    Step 4: Allocate retrieval budget based on route scores.

    Returns a RetrievalBudget specifying whether to retrieve,
    how much to retrieve, and which routes to activate.
    """

    selected_routes: list[str] = []
    reasoning_parts: list[str] = []

    # ── Rule 1: Conversation alone can answer ────────────────
    if route_scores.conversation_score >= settings.conversation_confidence_threshold:
        logger.info(
            "budget_skip_retrieval",
            reason="conversation_confidence_high",
            score=route_scores.conversation_score,
        )
        return RetrievalBudget(
            retrieve=False,
            budget_level="skip",
            selected_routes=["conversation"],
            top_k=0,
            reasoning=f"Conversation confidence {route_scores.conversation_score:.2f} >= {settings.conversation_confidence_threshold} — skipping retrieval",
        )

    # ── Rule 2: Memory alone can answer ──────────────────────
    if route_scores.memory_score >= settings.memory_confidence_threshold:
        selected_routes.append("memory")
        reasoning_parts.append(
            f"memory_confidence={route_scores.memory_score:.2f} (high)"
        )
        # Still do minimal document retrieval for verification
        if route_scores.document_score > 0.3:
            selected_routes.append("document")
            reasoning_parts.append("document added for verification")
            return RetrievalBudget(
                retrieve=True,
                budget_level="low",
                selected_routes=selected_routes,
                top_k=settings.retrieval_budget_low_top_k,
                reasoning=" | ".join(reasoning_parts),
            )
        return RetrievalBudget(
            retrieve=True,
            budget_level="low",
            selected_routes=selected_routes,
            top_k=settings.retrieval_budget_low_top_k,
            reasoning=" | ".join(reasoning_parts),
        )

    # ── Rule 3: Build route list from scores ─────────────────
    if route_scores.conversation_score > 0.3:
        selected_routes.append("conversation")

    if route_scores.memory_score > 0.3:
        selected_routes.append("memory")

    if route_scores.document_score > 0.3:
        selected_routes.append("document")

    if route_scores.fresh_score > settings.fresh_data_confidence_threshold:
        selected_routes.append("fresh")

    # Ensure at least document route is selected
    if "document" not in selected_routes:
        selected_routes.append("document")

    # ── Rule 4: Determine budget level ───────────────────────
    max_score = max(
        route_scores.conversation_score,
        route_scores.memory_score,
        route_scores.document_score,
        route_scores.fresh_score,
    )

    if max_score >= 0.5:
        budget_level = "medium"
        top_k = settings.retrieval_budget_medium_top_k
        reasoning_parts.append(f"max_route_score={max_score:.2f} (moderate)")
    else:
        budget_level = "high"
        top_k = settings.retrieval_budget_high_top_k
        reasoning_parts.append(f"max_route_score={max_score:.2f} (low) — high budget")

    # Complex queries always get at least medium budget
    if query_analysis.complexity_score >= 0.5 and budget_level != "high":
        budget_level = "medium"
        top_k = max(top_k, settings.retrieval_budget_medium_top_k)
        reasoning_parts.append("complexity boost applied")

    budget = RetrievalBudget(
        retrieve=True,
        budget_level=budget_level,
        selected_routes=selected_routes,
        top_k=top_k,
        reasoning=" | ".join(reasoning_parts),
    )

    logger.info(
        "budget_allocated",
        level=budget.budget_level,
        routes=budget.selected_routes,
        top_k=budget.top_k,
    )

    return budget


import time


async def step4_retrieval_budget_node(state: dict) -> dict:
    """LangGraph node for Step 4: Retrieval Budget."""
    t0 = time.perf_counter()
    budget = await allocate_budget(state["route_scores"], state["query_analysis"])
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "budget": budget,
        "step_timings": {"step4_retrieval_budget": elapsed}
    }


