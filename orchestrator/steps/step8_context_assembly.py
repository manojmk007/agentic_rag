"""
orchestrator/steps/step8_context_assembly.py
==============================================
Step 8 — Context Assembly Engine.

Builds the final context package from:
  1. Conversation context (recent turns)
  2. User context (session metadata)
  3. Memory context (relevant memories)
  4. Retrieved evidence (deduplicated, ranked)
  5. Tool outputs (future)

Processing:
  - Deduplicate across sources
  - Remove low-confidence evidence
  - Prioritize by relevance → recency → confidence
  - Truncate to fit token budget
"""

from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.context_models import ContextPackage, ContextQuality, RetrievedChunk
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)

# Rough token estimation: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


@track_latency("step8_context_assembly")
async def assemble_context(
    conversation_state: ConversationState,
    memories: list[dict],
    retrieved_chunks: list[RetrievedChunk],
    quality: ContextQuality,
    max_tokens: int = None,
    session_metadata: dict = None,
) -> ContextPackage:
    """
    Step 8: Assemble the final context package for downstream LLM.

    Prioritizes and deduplicates evidence, fits within token budget.
    """
    max_tokens = max_tokens or settings.max_context_tokens

    # ── 1. Conversation context ──────────────────────────────
    conv_context = _build_conversation_context(conversation_state)

    # ── 2. User context ──────────────────────────────────────
    user_context = _build_user_context(conversation_state, session_metadata)

    # ── 3. Memory context ────────────────────────────────────
    memory_context = _build_memory_context(memories)

    # ── 4. Retrieved evidence ────────────────────────────────
    evidence = _build_evidence(retrieved_chunks, quality)

    # ── 5. Estimate tokens and truncate ──────────────────────
    total_chars = (
        _estimate_chars(conv_context)
        + _estimate_chars_dict(user_context)
        + _estimate_chars(memory_context)
        + _estimate_chars(evidence)
    )
    total_tokens_estimate = total_chars // _CHARS_PER_TOKEN

    # If over budget, trim evidence first, then memories, then conversation
    if total_tokens_estimate > max_tokens:
        evidence, memory_context, conv_context = _truncate_to_budget(
            evidence, memory_context, conv_context, max_tokens
        )
        total_chars = (
            _estimate_chars(conv_context)
            + _estimate_chars_dict(user_context)
            + _estimate_chars(memory_context)
            + _estimate_chars(evidence)
        )
        total_tokens_estimate = total_chars // _CHARS_PER_TOKEN

    package = ContextPackage(
        conversation_context=conv_context,
        user_context=user_context,
        retrieved_evidence=evidence,
        memory_context=memory_context,
        tool_outputs=[],
        total_tokens_estimate=total_tokens_estimate,
    )

    logger.info(
        "context_assembled",
        conv_turns=len(conv_context),
        memories=len(memory_context),
        evidence=len(evidence),
        tokens_estimate=total_tokens_estimate,
    )

    return package


def _build_conversation_context(conv: ConversationState) -> list[dict]:
    """Extract recent conversation turns as context."""
    context = []

    # Include summary of older turns if available
    if conv.conversation_summary:
        context.append({
            "role": "system",
            "content": f"[Conversation Summary] {conv.conversation_summary}",
            "type": "summary",
        })

    # Include recent full turns
    for turn in conv.recent_turns:
        context.append({
            "role": turn.role,
            "content": turn.content,
            "type": "turn",
            "topic": turn.topic,
        })

    return context


def _build_user_context(
    conv: ConversationState, session_metadata: dict = None
) -> dict:
    """Build user/session context dict."""
    ctx = {
        "current_topic": conv.current_topic,
        "turn_count": conv.turn_count,
    }
    if session_metadata:
        ctx.update(session_metadata)
    return ctx


def _build_memory_context(memories: list[dict]) -> list[dict]:
    """Format memories for context injection."""
    context = []
    for m in memories:
        context.append({
            "query": m.get("query", ""),
            "answer": m.get("answer", ""),
            "category": m.get("category", ""),
            "confidence": m.get("confidence", 0.0),
            "score": m.get("score", 0.0),
        })
    return context


def _build_evidence(
    chunks: list[RetrievedChunk], quality: ContextQuality
) -> list[dict]:
    """
    Build evidence list from retrieved chunks.
    Deduplicate and sort by relevance.
    """
    # Deduplicate by text content (first 200 chars)
    seen_texts: set[str] = set()
    unique_chunks: list[dict] = []

    for chunk in chunks:
        text_key = chunk.text[:200].lower().strip()
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        unique_chunks.append({
            "id": chunk.id,
            "text": chunk.text,
            "score": chunk.score,
            "source": chunk.source,
            "metadata": chunk.metadata,
        })

    # Sort by score descending
    unique_chunks.sort(key=lambda c: c.get("score", 0.0), reverse=True)

    return unique_chunks


def _estimate_chars(items: list) -> int:
    """Rough character count for a list of dicts/strings."""
    total = 0
    for item in items:
        if isinstance(item, dict):
            for v in item.values():
                total += len(str(v))
        else:
            total += len(str(item))
    return total


def _estimate_chars_dict(d: dict) -> int:
    """Rough character count for a dict."""
    return sum(len(str(v)) for v in d.values())


def _truncate_to_budget(
    evidence: list[dict],
    memories: list[dict],
    conv_context: list[dict],
    max_tokens: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Progressively truncate components to fit within token budget.
    Priority: keep conversation > memories > evidence (trim evidence first).
    """
    max_chars = max_tokens * _CHARS_PER_TOKEN

    # Trim evidence
    while evidence and _estimate_chars(evidence) + _estimate_chars(memories) + _estimate_chars(conv_context) > max_chars:
        evidence.pop()

    # Trim memories if still over
    while memories and _estimate_chars(evidence) + _estimate_chars(memories) + _estimate_chars(conv_context) > max_chars:
        memories.pop()

    # Trim conversation if still over (keep at least last 2 turns)
    while len(conv_context) > 2 and _estimate_chars(evidence) + _estimate_chars(memories) + _estimate_chars(conv_context) > max_chars:
        conv_context.pop(0)  # Remove oldest

    return evidence, memories, conv_context


import time


async def step8_context_assembly_node(state: dict) -> dict:
    """LangGraph node for Step 8: Context Assembly."""
    t0 = time.perf_counter()
    chunks_as_obj = [RetrievedChunk(**c) for c in state["retrieved_chunks"]]
    session_metadata = {"tenant_id": state["tenant_id"]} if state.get("tenant_id") else None

    context_package = await assemble_context(
        conversation_state=state["conversation_state"],
        memories=state["memories"],
        retrieved_chunks=chunks_as_obj,
        quality=state["quality"],
        session_metadata=session_metadata,
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "context_package": context_package,
        "step_timings": {"step8_context_assembly": elapsed}
    }


