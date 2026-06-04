"""
Tests for Step 1 — Query Understanding.
"""

import pytest
from orchestrator.steps.step1_query_understanding import (
    _fast_classify,
    _compute_complexity,
    _compute_ambiguity,
    _extract_temporal_signals,
)
from orchestrator.models.query_models import QueryType


class TestFastClassify:
    """Test the fast-path heuristic classifier."""

    def test_greeting_detected(self):
        assert _fast_classify("Hello") == QueryType.CONVERSATION
        assert _fast_classify("hi") == QueryType.CONVERSATION
        assert _fast_classify("thanks") == QueryType.CONVERSATION

    def test_memory_query_detected(self):
        assert _fast_classify("What did we decide about the database?") == QueryType.MEMORY
        assert _fast_classify("What was our decision?") == QueryType.MEMORY
        assert _fast_classify("You mentioned something earlier") == QueryType.MEMORY

    def test_followup_detected(self):
        assert _fast_classify("Tell me more about that") == QueryType.FOLLOW_UP
        assert _fast_classify("Elaborate on that point") == QueryType.FOLLOW_UP

    def test_complex_query_returns_none(self):
        """Complex queries should NOT be fast-classified."""
        assert _fast_classify("Compare the trade-offs between SQL and NoSQL") is None
        assert _fast_classify("What is photosynthesis?") is None

    def test_empty_query(self):
        result = _fast_classify("")
        # Empty query should not match any pattern
        assert result is None


class TestComplexityScoring:
    """Test complexity score computation."""

    def test_simple_query_low_score(self):
        score = _compute_complexity("What is the capital of France?")
        assert score < 0.4

    def test_complex_query_high_score(self):
        score = _compute_complexity(
            "Compare the trade-offs between microservices and monolithic architecture"
        )
        assert score >= 0.4

    def test_multi_clause_query(self):
        score = _compute_complexity(
            "What are the causes, effects, and potential solutions for climate change?"
        )
        assert score > 0.3

    def test_very_long_query(self):
        score = _compute_complexity(
            "Can you explain in detail the differences between neural networks "
            "and traditional machine learning approaches and their applications "
            "in modern data science workflows?"
        )
        assert score >= 0.3


class TestAmbiguityScoring:
    """Test ambiguity detection."""

    def test_clear_query_low_ambiguity(self):
        score = _compute_ambiguity("What is photosynthesis?", QueryType.DOCUMENT)
        assert score < 0.4

    def test_pronoun_heavy_query(self):
        score = _compute_ambiguity("Tell me more about it and that", QueryType.FOLLOW_UP)
        assert score > 0.3

    def test_very_short_query(self):
        score = _compute_ambiguity("Why?", QueryType.FOLLOW_UP)
        assert score > 0.3

    def test_specific_query_no_ambiguity(self):
        score = _compute_ambiguity(
            "What is the molecular weight of water?",
            QueryType.DOCUMENT,
        )
        assert score < 0.3


class TestTemporalSignals:
    """Test temporal signal extraction."""

    def test_year_detected(self):
        signals = _extract_temporal_signals("What happened in 2025?")
        assert "2025" in signals

    def test_recency_words(self):
        signals = _extract_temporal_signals("Show me the latest reports")
        assert any("latest" in s.lower() for s in signals)

    def test_no_temporal_signals(self):
        signals = _extract_temporal_signals("What is photosynthesis?")
        assert len(signals) == 0
