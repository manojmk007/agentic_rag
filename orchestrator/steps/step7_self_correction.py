"""
orchestrator/steps/step7_self_correction.py
=============================================
Step 7 — Self-Correction Controller.

When context quality is weak:
  Retry 1: Query Rewrite — rewrite query with broader terms
  Retry 2: Query Expansion — maximally expand search scope
  Beyond max: Recommend asking user for clarification

Tracks correction history to avoid repeating strategies.
"""

from orchestrator.models.context_models import ContextQuality
from orchestrator.models.routing_models import RetrievalBudget
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


@track_latency("step7_self_correction")
async def correct(
    quality: ContextQuality,
    current_budget: RetrievalBudget,
    retry_count: int,
    max_retries: int = None,
) -> tuple[RetrievalBudget, bool, str]:
    """
    Step 7: Determine if self-correction is needed and what strategy to use.

    Args:
        quality: Current context quality assessment.
        current_budget: Current retrieval budget.
        retry_count: How many retries have been attempted.
        max_retries: Maximum allowed retries (default from settings).

    Returns:
        (new_budget, should_retry, strategy_description)
        If should_retry is False and retries are exhausted, the orchestrator
        should flag the response for clarification.
    """
    max_retries = max_retries or settings.max_self_correction_retries

    # ── If quality is sufficient, no correction needed ───────
    if quality.verdict == "sufficient":
        return current_budget, False, "quality_sufficient"

    # ── If retries exhausted, recommend clarification ────────
    if retry_count >= max_retries:
        logger.info(
            "self_correction_exhausted",
            retries=retry_count,
            max=max_retries,
            verdict=quality.verdict,
            confidence=quality.evidence_confidence,
        )
        return current_budget, False, "retries_exhausted_ask_clarification"

    # ── Apply correction strategy based on retry count ───────

    if retry_count == 0:
        # Strategy 1: Query Rewrite
        # The optimizer (Step 5) will handle the rewrite with retry_count=1
        new_budget = _escalate_budget(current_budget, strategy="rewrite")
        strategy = "query_rewrite"

    elif retry_count == 1:
        # Strategy 2: Query Expansion
        # The optimizer (Step 5) will handle expansion with retry_count=2
        new_budget = _escalate_budget(current_budget, strategy="expand")
        strategy = "query_expansion"

    else:
        # Should not reach here due to max_retries check above
        return current_budget, False, "unexpected_retry_count"

    logger.info(
        "self_correction_triggered",
        retry=retry_count + 1,
        strategy=strategy,
        old_budget=current_budget.budget_level,
        new_budget=new_budget.budget_level,
        quality_verdict=quality.verdict,
        evidence_confidence=quality.evidence_confidence,
    )

    return new_budget, True, strategy


def _escalate_budget(
    budget: RetrievalBudget, strategy: str
) -> RetrievalBudget:
    """
    Escalate the retrieval budget for the next retry.

    Strategy 'rewrite': increase top_k by 1.5x
    Strategy 'expand': max budget, all sources
    """
    if strategy == "rewrite":
        new_top_k = min(int(budget.top_k * 1.5), settings.retrieval_budget_high_top_k)
        new_level = "medium" if budget.budget_level == "low" else budget.budget_level
        new_routes = list(budget.selected_routes)
        if "document" not in new_routes:
            new_routes.append("document")

        return RetrievalBudget(
            retrieve=True,
            budget_level=new_level,
            selected_routes=new_routes,
            top_k=new_top_k,
            reasoning=f"self_correction_rewrite: top_k {budget.top_k} → {new_top_k}",
        )

    elif strategy == "expand":
        return RetrievalBudget(
            retrieve=True,
            budget_level="high",
            selected_routes=["conversation", "memory", "document"],
            top_k=settings.retrieval_budget_high_top_k,
            reasoning="self_correction_expand: maximum budget with all sources",
        )

    return budget


import time


async def step7_self_correction_node(state: dict) -> dict:
    """LangGraph node for Step 7: Self-Correction Control."""
    t0 = time.perf_counter()
    retry_count = state["retry_count"]
    new_budget, should_retry, strategy = await correct(
        state["quality"], state["budget"], retry_count
    )

    updates = {
        "budget": new_budget,
        "step_timings": {f"step7_self_correction_r{retry_count}": round((time.perf_counter() - t0) * 1000, 2)}
    }

    if should_retry:
        updates["retry_count"] = retry_count + 1
    else:
        if strategy == "retries_exhausted_ask_clarification" and state["quality"].verdict != "sufficient":
            updates["needs_clarification"] = True
            updates["clarification_reason"] = (
                f"Unable to find sufficient evidence after {retry_count} retries. "
                f"Evidence confidence: {state['quality'].evidence_confidence:.2f}. "
                f"Missing aspects: {', '.join(state['quality'].missing_aspects[:5])}."
            )

    return updates


