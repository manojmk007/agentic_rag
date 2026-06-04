"""
orchestrator/steps/step3_route_scoring.py
===========================================
Step 3 — Route Scoring Engine.

Independently evaluates 4 retrieval routes:
  - Conversation: can existing conversation context answer?
  - Memory: can stored memories/preferences answer?
  - Document: does the query need document retrieval?
  - Fresh Data: does the query need live/recent data?

Each route gets a confidence score [0.0, 1.0].
"""

from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.routing_models import RouteScores
from orchestrator.services.memory_store import memory_store
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


@track_latency("step3_route_scoring")
async def score_routes(
    query_analysis: QueryAnalysis,
    conversation_state: ConversationState,
) -> RouteScores:
    """
    Step 3: Score each retrieval route independently.

    Returns RouteScores with 4 independent confidence values.
    """

    conv_score = _score_conversation_route(query_analysis, conversation_state)
    mem_score = await _score_memory_route(query_analysis, conversation_state)
    doc_score = _score_document_route(query_analysis, conversation_state)
    fresh_score = _score_fresh_data_route(query_analysis)

    scores = RouteScores(
        conversation_score=round(conv_score, 4),
        memory_score=round(mem_score, 4),
        document_score=round(doc_score, 4),
        fresh_score=round(fresh_score, 4),
    )

    logger.info(
        "routes_scored",
        conversation=scores.conversation_score,
        memory=scores.memory_score,
        document=scores.document_score,
        fresh=scores.fresh_score,
    )

    return scores


def _score_conversation_route(
    analysis: QueryAnalysis, conv: ConversationState
) -> float:
    """Score the conversation route based on context availability."""
    score = conv.conversation_confidence

    # Boost if follow-up
    if conv.followup:
        score = max(score, 0.6)

    # Penalize if context switch
    if conv.context_switch:
        score *= 0.3

    # Conversational queries = high conversation score
    if analysis.query_type == QueryType.CONVERSATION:
        score = max(score, 0.95)

    # If no conversation history, can't use this route
    if conv.turn_count == 0:
        score = 0.0

    return min(score, 1.0)


async def _score_memory_route(
    analysis: QueryAnalysis, conv: ConversationState
) -> float:
    """Score the memory route based on query type and memory availability."""
    score = 0.0

    # Memory-type queries get a strong base score
    if analysis.query_type == QueryType.MEMORY:
        score += 0.7

    # Check if we actually have relevant memories
    try:
        memories = await memory_store.search_memories(
            conv.resolved_query or analysis.objective,
            limit=1,
        )
        if memories:
            best_score = memories[0].get("score", 0.0)
            score = max(score, best_score)
    except Exception:
        pass  # Memory store may not be available

    # Follow-ups about previous topics may benefit from memory
    if conv.followup and conv.turn_count > 3:
        score += 0.1

    return min(score, 1.0)


def _score_document_route(
    analysis: QueryAnalysis, conv: ConversationState
) -> float:
    """Score the document route based on query complexity and novelty."""
    score = 0.0

    # Document/Hybrid queries = strong document signal
    if analysis.query_type in (QueryType.DOCUMENT, QueryType.HYBRID):
        score += 0.7

    # Complex queries need document evidence
    score += analysis.complexity_score * 0.3

    # If query requires context, documents are likely needed
    if analysis.requires_context:
        score += 0.2

    # Novel entities (not in conversation) suggest document need
    if analysis.entities and conv.turn_count > 0:
        conv_entity_set = set(
            e.lower() for t in conv.recent_turns for e in t.entities
        )
        novel = [e for e in analysis.entities if e.lower() not in conv_entity_set]
        if novel:
            score += min(len(novel) * 0.1, 0.2)

    # Conversational or memory queries don't need documents
    if analysis.query_type in (QueryType.CONVERSATION, QueryType.MEMORY):
        score *= 0.2

    return min(score, 1.0)


def _score_fresh_data_route(analysis: QueryAnalysis) -> float:
    """Score the fresh data route based on temporal signals."""
    score = 0.0

    # Temporal signals are the primary indicator
    if analysis.temporal_signals:
        score += 0.3 * len(analysis.temporal_signals)

    # FreshData query type
    if analysis.query_type == QueryType.FRESH_DATA:
        score += 0.5

    # Keywords suggesting recency
    q = analysis.objective.lower() if analysis.objective else ""
    recency_words = {"latest", "newest", "current", "now", "today", "live", "real-time"}
    if any(w in q for w in recency_words):
        score += 0.2

    return min(score, 1.0)


import time


async def step3_route_scoring_node(state: dict) -> dict:
    """LangGraph node for Step 3: Route Scoring."""
    t0 = time.perf_counter()
    route_scores = await score_routes(state["query_analysis"], state["conversation_state"])
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "route_scores": route_scores,
        "step_timings": {"step3_route_scoring": elapsed}
    }


