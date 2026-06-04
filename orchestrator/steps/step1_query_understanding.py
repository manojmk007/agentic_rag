"""
orchestrator/steps/step1_query_understanding.py
=================================================
Step 1 — Query Understanding Engine.

Analyzes the incoming query to extract:
  - Intent (lookup, compare, explain, recall, execute, converse)
  - Domain (technical, scientific, business, general)
  - Entities (named entities, technical terms)
  - Ambiguity score
  - Query type classification
  - Complexity score
  - Temporal signals

Uses a fast-path heuristic for obvious cases and LLM for complex analysis.
"""

import re
from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.services.llm_service import llm_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)

# ── Fast-Path Signal Patterns ────────────────────────────────

_GREETING_SIGNALS = {
    "hello", "hi", "hey", "thanks", "thank you", "okay", "ok",
    "sure", "got it", "cool", "nice", "great", "bye", "goodbye",
}

_MEMORY_SIGNALS = [
    r"what did (?:we|i|you)",
    r"what was (?:our|my|the)",
    r"last time",
    r"previously",
    r"remember when",
    r"(?:our|my) (?:decision|preference|project)",
    r"we (?:chose|decided|discussed|agreed)",
    r"you (?:mentioned|said|told)",
    r"earlier (?:we|you|i)",
    r"continue (?:my|our|the)",
]

_FOLLOWUP_SIGNALS = [
    r"^(?:tell me more|more about|elaborate|explain further|go on|continue)",
    r"^(?:what about|how about|and |also )",
    r"^(?:why|how)\??\s*$",
    r"^(?:yes|no|maybe),?\s",
]

_TEMPORAL_PATTERNS = [
    r"\b(?:latest|newest|recent|current|today|yesterday|tomorrow)\b",
    r"\b(?:20\d{2})\b",
    r"\b(?:this (?:week|month|year|quarter))\b",
    r"\b(?:last (?:week|month|year|quarter))\b",
]

_COMPLEX_SIGNALS = [
    r"\b(?:compare|comparison|versus|vs\.?)\b",
    r"\b(?:analyze|analyse|analysis|evaluate)\b",
    r"\b(?:explain (?:why|how))\b",
    r"\b(?:trade-?offs?|pros and cons|implications)\b",
    r"\b(?:relationship between|difference between)\b",
    r"\b(?:summarize|summarise|overview)\b",
]

_TASK_SIGNALS = [
    r"\b(?:create|generate|build|make|write|delete|update|run|execute)\b",
    r"\b(?:upload|download|send|deploy|configure|set up)\b",
]


def _count_tokens(text: str) -> int:
    return len(text.split())


def _has_pattern(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _extract_temporal_signals(text: str) -> list[str]:
    found = []
    for pattern in _TEMPORAL_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.extend(matches)
    return found


def _fast_classify(query: str) -> QueryType | None:
    """
    Fast-path heuristic classification for obvious query types.
    Returns None if LLM analysis is needed.
    """
    q = query.lower().strip()
    tokens = q.split()

    # Greetings / conversational
    if len(tokens) <= 4 and any(t in _GREETING_SIGNALS for t in tokens):
        return QueryType.CONVERSATION

    # Memory recall
    if _has_pattern(q, _MEMORY_SIGNALS):
        return QueryType.MEMORY

    # Follow-up
    if _has_pattern(q, _FOLLOWUP_SIGNALS):
        return QueryType.FOLLOW_UP

    return None


def _compute_complexity(query: str) -> float:
    """Heuristic complexity score [0, 1]."""
    q = query.lower()
    score = 0.0

    token_count = _count_tokens(query)
    if token_count > 15:
        score += 0.2
    if token_count > 30:
        score += 0.1

    if _has_pattern(q, _COMPLEX_SIGNALS):
        score += 0.3

    if q.count(" and ") >= 1 and q.count(",") >= 2:
        score += 0.35
    elif q.count(" and ") >= 2 or q.count(",") >= 3:
        score += 0.15

    deep_words = {"why", "how", "compare", "explain", "analyze", "analyse"}
    if set(q.split()) & deep_words:
        score += 0.1

    # Multiple question marks or sub-questions
    if q.count("?") >= 2:
        score += 0.15

    return min(score, 1.0)


def _compute_ambiguity(query: str, query_type: QueryType) -> float:
    """Estimate ambiguity: how likely the query has multiple interpretations."""
    q = query.lower().strip()
    score = 0.0

    token_count = _count_tokens(query)
    if token_count <= 3:
        score += 0.3  # very short queries are often ambiguous

    # Pronouns without clear referents
    pronouns = {"it", "this", "that", "they", "them", "those", "these", "its"}
    query_tokens = set(q.split())
    pronoun_count = len(query_tokens & pronouns)
    score += pronoun_count * 0.15

    # Follow-ups are inherently ambiguous without context
    if query_type == QueryType.FOLLOW_UP:
        score += 0.2

    # Vague verbs
    vague = {"works", "work", "use", "do", "does", "mean", "means"}
    if query_tokens & vague:
        score += 0.1

    return min(score, 1.0)


@track_latency("step1_query_understanding")
async def analyze_query(
    query: str,
    conversation_history: list[dict] = None,
) -> QueryAnalysis:
    """
    Step 1: Analyze and classify the user query.

    Uses fast-path heuristics for obvious cases.
    Falls back to LLM for complex intent/entity extraction.
    """
    conversation_history = conversation_history or []

    # ── Fast-path classification ─────────────────────────────
    fast_type = _fast_classify(query)
    complexity = _compute_complexity(query)
    temporal = _extract_temporal_signals(query)

    if fast_type == QueryType.CONVERSATION:
        return QueryAnalysis(
            intent="converse",
            domain="general",
            confidence=0.95,
            ambiguity_score=0.0,
            entities=[],
            query_type=QueryType.CONVERSATION,
            objective="Casual conversation or acknowledgment",
            complexity_score=0.0,
            requires_context=False,
            temporal_signals=temporal,
        )

    # ── LLM-powered analysis ─────────────────────────────────
    history_context = ""
    if conversation_history:
        recent = conversation_history[-3:]
        history_lines = [
            f"{t.get('role', 'user')}: {t.get('content', '')[:100]}"
            for t in recent
        ]
        history_context = f"\nRecent conversation:\n" + "\n".join(history_lines)

    prompt = f"""Analyze this user query for an AI assistant system.
{history_context}

Query: "{query}"

Extract:
1. intent: What does the user want? One of: lookup, compare, explain, recall, execute, converse, clarify
2. domain: One of: technical, scientific, business, legal, medical, general
3. entities: List of named entities, technical terms, and key concepts mentioned
4. objective: One-sentence description of what the user wants to achieve
5. requires_context: Does this need external knowledge to answer? (true/false)

Return JSON:
{{"intent":"...","domain":"...","entities":["..."],"objective":"...","requires_context":true}}"""

    try:
        result = await llm_service.generate_json(prompt, is_complex=False)

        intent = result.get("intent", "lookup")
        domain = result.get("domain", "general")
        entities = result.get("entities", [])
        objective = result.get("objective", "")
        requires_ctx = result.get("requires_context", True)

        # Determine query type from intent + signals
        if fast_type:
            query_type = fast_type
        elif intent == "recall":
            query_type = QueryType.MEMORY
        elif intent == "execute":
            query_type = QueryType.TASK_EXECUTION
        elif temporal:
            query_type = QueryType.FRESH_DATA
        elif complexity >= 0.5:
            query_type = QueryType.HYBRID
        elif intent in ("lookup", "explain", "compare"):
            query_type = QueryType.DOCUMENT
        else:
            query_type = QueryType.DOCUMENT

        ambiguity = _compute_ambiguity(query, query_type)

        analysis = QueryAnalysis(
            intent=intent,
            domain=domain,
            confidence=0.85,
            ambiguity_score=round(ambiguity, 3),
            entities=entities if isinstance(entities, list) else [],
            query_type=query_type,
            objective=objective,
            complexity_score=round(complexity, 3),
            requires_context=requires_ctx,
            temporal_signals=temporal,
        )

        logger.info(
            "query_analyzed",
            intent=analysis.intent,
            type=analysis.query_type.value,
            complexity=analysis.complexity_score,
            ambiguity=analysis.ambiguity_score,
            entities_count=len(analysis.entities),
        )
        return analysis

    except Exception as e:
        logger.warning("llm_analysis_failed_using_heuristic", error=str(e))
        # Fallback: pure heuristic
        query_type = fast_type or QueryType.DOCUMENT
        ambiguity = _compute_ambiguity(query, query_type)

        return QueryAnalysis(
            intent="lookup",
            domain="general",
            confidence=0.5,
            ambiguity_score=round(ambiguity, 3),
            entities=[],
            query_type=query_type,
            objective=query,
            complexity_score=round(complexity, 3),
            requires_context=True,
            temporal_signals=temporal,
        )


import time


async def step1_query_understanding_node(state: dict) -> dict:
    """LangGraph node for Step 1: Query Understanding."""
    t0 = time.perf_counter()
    query_analysis = await analyze_query(state["query"], state["conversation_history"])
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "query_analysis": query_analysis,
        "step_timings": {"step1_query_understanding": elapsed}
    }

