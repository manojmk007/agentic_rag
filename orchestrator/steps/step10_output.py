"""
orchestrator/steps/step10_output.py
=====================================
Step 10 — Final Output Formatter.

Assembles the structured JSON output from all step results.
This is the ONLY thing returned to the downstream system.
"""

from orchestrator.models.query_models import QueryAnalysis
from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.routing_models import RouteScores, RetrievalBudget
from orchestrator.models.context_models import ContextQuality, ContextPackage, RiskAssessment
from orchestrator.models.output_models import OrchestratorOutput
from orchestrator.services.observability import get_logger

logger = get_logger(__name__)


def format_output(
    query_analysis: QueryAnalysis,
    conversation_state: ConversationState,
    route_scores: RouteScores,
    budget: RetrievalBudget,
    quality: ContextQuality,
    context_package: ContextPackage,
    risk: RiskAssessment,
    step_timings: dict,
    self_correction_count: int = 0,
    needs_clarification: bool = False,
    clarification_reason: str = "",
) -> OrchestratorOutput:
    """
    Step 10: Assemble the final OrchestratorOutput.

    This is a pure formatting step — no async, no I/O.
    """

    # ── Compute orchestrator confidence ──────────────────────
    orchestrator_confidence = _compute_orchestrator_confidence(
        quality, risk, conversation_state, budget
    )

    output = OrchestratorOutput(
        intent=query_analysis.intent,
        topic=conversation_state.current_topic,
        entities=query_analysis.entities,
        selected_routes=budget.selected_routes,
        retrieval_required=budget.retrieve,
        budget_level=budget.budget_level,
        evidence_confidence=quality.evidence_confidence,
        context_package=context_package,
        risk_flags=risk.flags,
        orchestrator_confidence=round(orchestrator_confidence, 4),
        resolved_query=conversation_state.resolved_query,
        needs_clarification=needs_clarification,
        clarification_reason=clarification_reason,
        self_correction_count=self_correction_count,
        metadata={
            "step_timings": step_timings,
            "query_type": query_analysis.query_type.value,
            "complexity_score": query_analysis.complexity_score,
            "ambiguity_score": query_analysis.ambiguity_score,
            "conversation_confidence": conversation_state.conversation_confidence,
            "route_scores": {
                "conversation": route_scores.conversation_score,
                "memory": route_scores.memory_score,
                "document": route_scores.document_score,
                "fresh": route_scores.fresh_score,
            },
            "budget_reasoning": budget.reasoning,
            "quality_verdict": quality.verdict,
            "risk_safe": risk.safe,
            "risk_blocked": risk.blocked,
        },
    )

    logger.info(
        "orchestrator_output_assembled",
        confidence=output.orchestrator_confidence,
        routes=output.selected_routes,
        retrieval=output.retrieval_required,
        clarification=output.needs_clarification,
        corrections=output.self_correction_count,
    )

    return output


def _compute_orchestrator_confidence(
    quality: ContextQuality,
    risk: RiskAssessment,
    conv: ConversationState,
    budget: RetrievalBudget,
) -> float:
    """
    Compute overall orchestrator confidence in the context package.

    Factors:
      - Evidence confidence (from quality evaluation)
      - Risk assessment (penalize if flagged)
      - Conversation confidence (if no retrieval, this is the main signal)
      - Budget satisfaction (was the budget sufficient?)
    """
    # Base from evidence or conversation
    if not budget.retrieve:
        # No retrieval — confidence comes from conversation
        base = conv.conversation_confidence
    else:
        # With retrieval — confidence comes from evidence
        base = quality.evidence_confidence

    # Risk penalty
    if risk.blocked:
        return 0.0
    if risk.flags:
        base *= 0.85  # 15% penalty per risk flag group

    # PII penalty
    if risk.pii_detected:
        base *= 0.9

    return min(base, 1.0)


import time

from orchestrator.steps.step6_context_quality import evaluate_quality


async def step10_output_node(state: dict) -> dict:
    """LangGraph node for Step 10: Final Output Formatter."""
    t0 = time.perf_counter()

    # If no retrieval happened, we might not have a quality object
    quality = state.get("quality")
    if not quality:
        quality = await evaluate_quality(
            state["query"], state["query_analysis"], [], state["memories"]
        )

    output = format_output(
        query_analysis=state["query_analysis"],
        conversation_state=state["conversation_state"],
        route_scores=state["route_scores"],
        budget=state["budget"],
        quality=quality,
        context_package=state["context_package"],
        risk=state["risk"],
        step_timings=state["step_timings"],
        self_correction_count=state["retry_count"],
        needs_clarification=state["needs_clarification"],
        clarification_reason=state["clarification_reason"],
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "output": output,
        "step_timings": {"step10_output": elapsed}
    }


