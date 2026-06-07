import pytest
from datetime import datetime, timezone
from app.core.validator import validate_response
from app.core.confidence_scorer import (
    score_citation_coverage,
    score_retrieval_relevance,
    score_answer_length,
)
from app.models.context import AssembledContext, SourceDocument
from app.models.response import LLMResponse


def make_llm_response(**overrides) -> LLMResponse:
    defaults = dict(
        response_id="resp_test_001",
        session_id="sess_001",
        raw_answer="Photosynthesis is the process by which plants convert sunlight into energy using chlorophyll.",
        source_ids=["src_001"],
        confidence_score=0.88,
        model_used="gemini/gemini-1.5-flash",
        prompt_tokens=200,
        completion_tokens=50,
        latency_ms=430.0,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return LLMResponse(**defaults)


def make_context(**overrides) -> AssembledContext:
    defaults = dict(
        session_id="sess_001",
        user_query="What is photosynthesis?",
        source_documents=[
            SourceDocument(source_id="src_001", content="Photosynthesis...", score=0.92),
            SourceDocument(source_id="src_002", content="Chlorophyll...", score=0.85),
        ],
    )
    defaults.update(overrides)
    return AssembledContext(**defaults)


# ── Citation coverage scorer ──────────────────────────────────────────────────

def test_citation_coverage_full():
    response = make_llm_response(source_ids=["src_001", "src_002"])
    ctx = make_context()
    score = score_citation_coverage(response, ctx)
    assert score == 1.0


def test_citation_coverage_partial():
    response = make_llm_response(source_ids=["src_001"])
    ctx = make_context()
    score = score_citation_coverage(response, ctx)
    assert score == 0.5


def test_citation_coverage_none_cited():
    response = make_llm_response(source_ids=[])
    ctx = make_context()
    score = score_citation_coverage(response, ctx)
    assert score == 0.0


def test_citation_coverage_no_sources_provided():
    response = make_llm_response(source_ids=[])
    ctx = make_context(source_documents=[])
    score = score_citation_coverage(response, ctx)
    assert score == 1.0  # not applicable — should not penalise


# ── Retrieval relevance scorer ────────────────────────────────────────────────

def test_retrieval_relevance_uses_cited_doc_scores():
    response = make_llm_response(source_ids=["src_001"])
    ctx = make_context()
    score = score_retrieval_relevance(response, ctx)
    assert score == 0.92   # src_001 has score 0.92


def test_retrieval_relevance_average_of_multiple():
    response = make_llm_response(source_ids=["src_001", "src_002"])
    ctx = make_context()
    score = score_retrieval_relevance(response, ctx)
    assert abs(score - 0.885) < 0.001   # (0.92 + 0.85) / 2


def test_retrieval_relevance_no_cited():
    response = make_llm_response(source_ids=[])
    ctx = make_context()
    score = score_retrieval_relevance(response, ctx)
    assert score == 0.0


# ── Answer length scorer ──────────────────────────────────────────────────────

def test_length_score_short_answer():
    response = make_llm_response(raw_answer="Yes.")
    score = score_answer_length(response)
    assert score == 0.3


def test_length_score_optimal_answer():
    words = " ".join(["word"] * 100)
    response = make_llm_response(raw_answer=words)
    score = score_answer_length(response)
    assert score == 1.0


# ── Full validation ───────────────────────────────────────────────────────────

def test_validation_passes_good_response():
    response = make_llm_response(
        confidence_score=0.88,
        source_ids=["src_001"],
    )
    ctx = make_context()
    result = validate_response(response, ctx)
    assert result.passed is True
    assert result.failure_reasons == []
    # With confidence=0.88, citation=0.5, relevance=0.92, length=~1.0
    # overall should comfortably exceed 0.65
    assert result.overall_score > 0.65


def test_validation_fails_low_confidence():
    response = make_llm_response(confidence_score=0.2)
    ctx = make_context()
    result = validate_response(response, ctx)
    assert result.passed is False
    assert any("Confidence" in r for r in result.failure_reasons)


def test_validation_fails_no_citations():
    response = make_llm_response(source_ids=[], confidence_score=0.9)
    ctx = make_context()
    result = validate_response(response, ctx)
    assert result.passed is False
    assert any("Citation" in r for r in result.failure_reasons)


def test_validation_flags_uncertainty_phrase():
    response = make_llm_response(
        raw_answer="I don't have enough information to answer this question.",
        confidence_score=0.85,
        source_ids=["src_001"],
    )
    ctx = make_context()
    result = validate_response(response, ctx)
    assert result.flagged_for_review is True


def test_validation_flags_very_short_answer():
    response = make_llm_response(raw_answer="Yes it is.")
    ctx = make_context()
    result = validate_response(response, ctx)
    assert result.flagged_for_review is True