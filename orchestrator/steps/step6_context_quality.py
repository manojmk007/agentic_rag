"""
orchestrator/steps/step6_context_quality.py
=============================================
Step 6 — Context Quality Evaluator.

Post-retrieval quality assessment:
  - Relevance: semantic similarity between query and chunks
  - Coverage: fraction of query entities present in context
  - Freshness: document recency metadata
  - Contradiction detection: conflicting claims across chunks
  - Duplicate detection: near-duplicate chunks
  - Missing aspect detection: uncovered query concepts

Returns verdict: sufficient, marginal, or insufficient.
"""

import re
from orchestrator.models.query_models import QueryAnalysis
from orchestrator.models.context_models import ContextQuality, RetrievedChunk
from orchestrator.services.embedder_service import embedder_service
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


@track_latency("step6_context_quality")
async def evaluate_quality(
    query: str,
    query_analysis: QueryAnalysis,
    retrieved_chunks: list[RetrievedChunk],
    memories: list[dict],
) -> ContextQuality:
    """
    Step 6: Evaluate the quality of retrieved context.

    Returns a ContextQuality object with scores and a verdict.
    """

    if not retrieved_chunks and not memories:
        return ContextQuality(
            coverage_score=0.0,
            relevance_score=0.0,
            freshness_score=0.0,
            conflict_detected=False,
            duplicate_count=0,
            missing_aspects=query_analysis.entities.copy(),
            evidence_confidence=0.0,
            verdict="insufficient",
        )

    # ── Relevance scoring ────────────────────────────────────
    relevance = await _compute_relevance(query, retrieved_chunks)

    # ── Coverage scoring ─────────────────────────────────────
    coverage, missing = _compute_coverage(query, query_analysis, retrieved_chunks, memories)

    # ── Freshness scoring ────────────────────────────────────
    freshness = _compute_freshness(retrieved_chunks)

    # ── Duplicate detection ──────────────────────────────────
    duplicate_count = _detect_duplicates(retrieved_chunks)

    # ── Contradiction detection ──────────────────────────────
    conflict_detected = _detect_contradictions(retrieved_chunks)

    # ── Composite confidence ─────────────────────────────────
    evidence_confidence = (
        0.40 * relevance
        + 0.30 * coverage
        + 0.20 * freshness
        + 0.10 * (1.0 if not conflict_detected else 0.5)
    )

    # Penalize for duplicates
    if duplicate_count > len(retrieved_chunks) * 0.5:
        evidence_confidence *= 0.8

    evidence_confidence = round(min(evidence_confidence, 1.0), 4)

    # ── Verdict ──────────────────────────────────────────────
    if evidence_confidence >= 0.6 and relevance >= settings.context_quality_min_relevance:
        verdict = "sufficient"
    elif evidence_confidence >= 0.35:
        verdict = "marginal"
    else:
        verdict = "insufficient"

    quality = ContextQuality(
        coverage_score=round(coverage, 4),
        relevance_score=round(relevance, 4),
        freshness_score=round(freshness, 4),
        conflict_detected=conflict_detected,
        duplicate_count=duplicate_count,
        missing_aspects=missing,
        evidence_confidence=evidence_confidence,
        verdict=verdict,
    )

    logger.info(
        "context_quality_evaluated",
        relevance=quality.relevance_score,
        coverage=quality.coverage_score,
        freshness=quality.freshness_score,
        confidence=quality.evidence_confidence,
        verdict=quality.verdict,
        conflicts=conflict_detected,
        duplicates=duplicate_count,
    )

    return quality


async def _compute_relevance(
    query: str, chunks: list[RetrievedChunk]
) -> float:
    """Compute average semantic relevance of chunks to query."""
    if not chunks:
        return 0.0

    # Use retrieval scores if available (already computed by retrieval backend)
    scores = [c.score for c in chunks if c.score > 0]
    if scores:
        # Normalize scores to [0, 1] range
        max_s = max(scores)
        if max_s > 1.0:
            scores = [s / max_s for s in scores]
        return sum(scores) / len(scores)

    # Fallback: compute embedding similarity
    try:
        query_vec = await embedder_service.embed_query(query)
        chunk_texts = [c.text for c in chunks[:5] if c.text]
        if not chunk_texts:
            return 0.0

        chunk_vecs = await embedder_service.embed_batch(chunk_texts)
        sims = [
            embedder_service.cosine_similarity(query_vec, cv)
            for cv in chunk_vecs
        ]
        return sum(sims) / len(sims) if sims else 0.0
    except Exception:
        return 0.3  # neutral fallback


def _compute_coverage(
    query: str,
    analysis: QueryAnalysis,
    chunks: list[RetrievedChunk],
    memories: list[dict],
) -> tuple[float, list[str]]:
    """
    Check what fraction of query concepts appear in the context.
    Returns (coverage_score, list_of_missing_aspects).
    """
    # Collect all query concepts
    concepts = set()
    for entity in analysis.entities:
        concepts.add(entity.lower())

    # Add key query terms
    stopwords = {
        "what", "is", "are", "the", "a", "an", "of", "in", "on",
        "to", "for", "with", "by", "from", "and", "or", "how", "why",
        "when", "where", "who", "which", "that", "this", "does", "do",
        "can", "could", "would", "should", "will", "did", "was", "were",
    }
    query_terms = {
        w.lower() for w in re.findall(r"\b\w+\b", query)
        if w.lower() not in stopwords and len(w) > 2
    }
    concepts.update(query_terms)

    if not concepts:
        return 0.5, []  # Neutral if no concepts

    # Build context text
    context_parts = [c.text.lower() for c in chunks if c.text]
    context_parts += [m.get("answer", "").lower() for m in memories]
    context_text = " ".join(context_parts)

    # Check coverage
    found = set()
    missing = []
    for concept in concepts:
        if concept in context_text:
            found.add(concept)
        else:
            missing.append(concept)

    coverage = len(found) / len(concepts) if concepts else 0.0
    return coverage, missing


def _compute_freshness(chunks: list[RetrievedChunk]) -> float:
    """Score freshness based on document metadata timestamps."""
    if not chunks:
        return 0.5  # neutral

    # Check if any chunks have timestamp metadata
    has_timestamps = False
    for c in chunks:
        if c.metadata.get("created_at") or c.metadata.get("date") or c.metadata.get("timestamp"):
            has_timestamps = True
            break

    if not has_timestamps:
        return 0.7  # assume reasonably fresh if no metadata

    # TODO: implement actual date parsing and recency scoring
    return 0.7


def _detect_duplicates(chunks: list[RetrievedChunk]) -> int:
    """Detect near-duplicate chunks by text similarity."""
    if len(chunks) < 2:
        return 0

    duplicates = 0
    seen_texts: list[str] = []

    for chunk in chunks:
        text = chunk.text[:200].lower().strip()
        if not text:
            continue
        for seen in seen_texts:
            # Simple overlap check
            if _text_overlap(text, seen) > 0.8:
                duplicates += 1
                break
        seen_texts.append(text)

    return duplicates


def _text_overlap(a: str, b: str) -> float:
    """Compute word-level Jaccard overlap between two texts."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _detect_contradictions(chunks: list[RetrievedChunk]) -> bool:
    """
    Basic contradiction detection.
    Checks for conflicting numerical claims or negation patterns.
    """
    if len(chunks) < 2:
        return False

    # Extract numerical claims
    number_claims: dict[str, set[str]] = {}
    for chunk in chunks:
        text = chunk.text.lower()
        # Find patterns like "X is Y" or "X = Y" where Y is a number
        matches = re.findall(
            r"(\b\w+(?:\s+\w+){0,2})\s+(?:is|are|was|were|equals?|=)\s+(\d+[\d,.]*)",
            text,
        )
        for subject, value in matches:
            subject = subject.strip()
            number_claims.setdefault(subject, set()).add(value)

    # Check for conflicting values for the same subject
    for subject, values in number_claims.items():
        if len(values) > 1:
            return True

    return False


import time


async def step6_context_quality_node(state: dict) -> dict:
    """LangGraph node for Step 6: Context Quality Evaluation."""
    t0 = time.perf_counter()
    chunks_as_obj = [RetrievedChunk(**c) for c in state["retrieved_chunks"]]
    quality = await evaluate_quality(
        state["query"], state["query_analysis"], chunks_as_obj, state["memories"]
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "quality": quality,
        "step_timings": {f"step6_quality_eval_r{state['retry_count']}": elapsed}
    }


