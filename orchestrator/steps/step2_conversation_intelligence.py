"""
orchestrator/steps/step2_conversation_intelligence.py
=======================================================
Step 2 — Conversation Intelligence Module.

Manages conversation state:
  - Coreference resolution (it, that, this → actual entities)
  - Topic tracking (continuity vs. context switch)
  - Follow-up detection
  - Conversation confidence scoring
  - Running summary of older turns (last 5 full, older summarized)
"""

import re

from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.conversation_models import ConversationState, ConversationTurn
from orchestrator.services.conversation_store import conversation_store
from orchestrator.services.llm_service import llm_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)

# ── Coreference Patterns ─────────────────────────────────────

_PRONOUN_PATTERNS = [
    (r"\bthat\b", "that"),
    (r"\bthis\b", "this"),
    (r"\bthose\b", "those"),
    (r"\bthese\b", "these"),
    (r"\b(?:it|its)\b", "it"),
    (r"\bthey\b", "they"),
    (r"\bthem\b", "them"),
]

_FOLLOWUP_PHRASES = [
    "tell me more",
    "more about",
    "elaborate",
    "explain further",
    "go on",
    "continue",
    "what about",
    "how about",
    "and also",
    "what else",
    "anything else",
    "can you explain",
    "why is that",
    "how so",
]


def _detect_pronouns(query: str) -> list[str]:
    """Detect unresolved pronouns in the query."""
    q = query.lower()
    found = []
    for pattern, label in _PRONOUN_PATTERNS:
        if re.search(pattern, q):
            found.append(label)
    return found


def _is_followup(query: str) -> bool:
    """Check if query is a follow-up to previous conversation."""
    q = query.lower().strip()
    # Direct follow-up phrases
    for phrase in _FOLLOWUP_PHRASES:
        if q.startswith(phrase) or phrase in q:
            return True
    # Very short query after conversation exists
    if len(q.split()) <= 3 and _detect_pronouns(q):
        return True
    return False


def _detect_topic_switch(
    query: str, current_topic: str, entities: list[str], prev_entities: list[str]
) -> bool:
    """Detect if the user has switched topics."""
    if not prev_entities:
        return False
    # If none of the previous entities appear in the current query/entities
    q_lower = query.lower()
    overlap = sum(1 for e in prev_entities if e.lower() in q_lower)
    entity_overlap = len(set(e.lower() for e in entities) & set(e.lower() for e in prev_entities))
    return overlap == 0 and entity_overlap == 0


@track_latency("step2_conversation_intelligence")
async def process_conversation(
    query: str,
    session_id: str,
    query_analysis: QueryAnalysis,
) -> ConversationState:
    """
    Step 2: Build conversation intelligence from session history.

    Resolves coreferences, tracks topics, computes conversation confidence.
    """

    # ── Retrieve conversation history ────────────────────────
    recent_turns, summary = await conversation_store.get_recent_and_summary(session_id)
    previous_entities = await conversation_store.get_last_entities(session_id)
    last_topic = await conversation_store.get_last_topic(session_id)

    # Build ConversationTurn objects
    turn_objects = [
        ConversationTurn(
            role=t.get("role", "user"),
            content=t.get("content", ""),
            entities=t.get("entities", []),
            topic=t.get("topic", "general"),
        )
        for t in recent_turns
    ]

    # ── Follow-up detection ──────────────────────────────────
    followup = _is_followup(query) or query_analysis.query_type == QueryType.FOLLOW_UP
    if not recent_turns:
        followup = False  # Can't be a follow-up if no history

    # ── Coreference resolution ───────────────────────────────
    pronouns = _detect_pronouns(query)
    resolved_query = query
    resolved_entities: list[str] = []

    if pronouns and recent_turns and previous_entities:
        # Attempt LLM-based resolution
        resolved_query, resolved_entities = await _resolve_coreferences(
            query, recent_turns, previous_entities, pronouns
        )

    # ── Topic detection ──────────────────────────────────────
    current_topic = query_analysis.domain
    if query_analysis.entities:
        current_topic = query_analysis.entities[0] if query_analysis.entities else query_analysis.domain

    context_switch = _detect_topic_switch(
        query, last_topic, query_analysis.entities, previous_entities
    )

    # Collect previous topics
    previous_topics = list(
        dict.fromkeys(t.get("topic", "general") for t in recent_turns if t.get("topic"))
    )

    # ── Conversation confidence ──────────────────────────────
    conv_confidence = _compute_conversation_confidence(
        query, recent_turns, followup, context_switch, query_analysis
    )

    state = ConversationState(
        followup=followup,
        context_switch=context_switch,
        resolved_entities=resolved_entities,
        resolved_query=resolved_query,
        conversation_confidence=round(conv_confidence, 4),
        current_topic=current_topic,
        previous_topics=previous_topics[-5:],
        conversation_summary=summary,
        recent_turns=turn_objects,
        turn_count=len(recent_turns),
    )

    logger.info(
        "conversation_processed",
        followup=followup,
        context_switch=context_switch,
        conv_confidence=state.conversation_confidence,
        resolved=len(resolved_entities),
        turns=state.turn_count,
    )

    return state


async def _resolve_coreferences(
    query: str,
    recent_turns: list[dict],
    previous_entities: list[str],
    pronouns: list[str],
) -> tuple[str, list[str]]:
    """Use LLM to resolve pronouns to actual entities from conversation context."""
    context_lines = []
    for t in recent_turns[-3:]:
        role = t.get("role", "user").capitalize()
        content = t.get("content", "")[:150]
        context_lines.append(f"{role}: {content}")

    prompt = f"""Given this conversation context:
{chr(10).join(context_lines)}

The user now says: "{query}"

The pronouns {pronouns} likely refer to entities from the conversation.
Known entities: {previous_entities[:10]}

Rewrite the user's query replacing all pronouns with the actual entities they refer to.
Return JSON: {{"resolved_query":"...","resolved_entities":["..."]}}"""

    try:
        result = await llm_service.generate_json(prompt, is_complex=False)
        resolved_query = result.get("resolved_query", query)
        resolved_entities = result.get("resolved_entities", [])
        if isinstance(resolved_entities, list):
            return resolved_query, resolved_entities
        return resolved_query, []
    except Exception as e:
        logger.warning("coreference_resolution_failed", error=str(e))
        return query, []


def _compute_conversation_confidence(
    query: str,
    recent_turns: list[dict],
    followup: bool,
    context_switch: bool,
    analysis: QueryAnalysis,
) -> float:
    """
    Compute confidence that conversation context alone can answer the query.
    High confidence → skip retrieval.
    """
    if not recent_turns:
        return 0.0

    confidence = 0.0

    # Follow-up queries are likely answerable from context
    if followup:
        confidence += 0.4

    # Context switch means context can't help
    if context_switch:
        return max(confidence - 0.3, 0.0)

    # Conversational queries don't need retrieval
    if analysis.query_type == QueryType.CONVERSATION:
        confidence += 0.5

    # More turns = more context available
    turn_bonus = min(len(recent_turns) / 10.0, 0.2)
    confidence += turn_bonus

    # If query entities overlap with conversation entities
    q_lower = query.lower()
    entity_hits = 0
    for turn in recent_turns[-3:]:
        for entity in turn.get("entities", []):
            if entity.lower() in q_lower:
                entity_hits += 1
    if entity_hits > 0:
        confidence += min(entity_hits * 0.1, 0.3)

    # If the query doesn't require context, conversation is sufficient
    if not analysis.requires_context:
        confidence += 0.3

    return min(confidence, 1.0)


import time


async def step2_conversation_intelligence_node(state: dict) -> dict:
    """LangGraph node for Step 2: Conversation Intelligence."""
    t0 = time.perf_counter()
    conversation_state = await process_conversation(
        state["query"], state["session_id"], state["query_analysis"]
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "conversation_state": conversation_state,
        "step_timings": {"step2_conversation_intelligence": elapsed}
    }


