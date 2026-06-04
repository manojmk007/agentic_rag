"""
Tests for Step 3 — Route Scoring.
"""

import pytest
from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.conversation_models import ConversationState, ConversationTurn
from orchestrator.steps.step3_route_scoring import (
    _score_conversation_route,
    _score_document_route,
    _score_fresh_data_route,
)


def _make_analysis(**kwargs) -> QueryAnalysis:
    defaults = {
        "intent": "lookup",
        "domain": "general",
        "confidence": 0.8,
        "ambiguity_score": 0.1,
        "entities": [],
        "query_type": QueryType.DOCUMENT,
        "objective": "test",
        "complexity_score": 0.3,
        "requires_context": True,
        "temporal_signals": [],
    }
    defaults.update(kwargs)
    return QueryAnalysis(**defaults)


def _make_conv(**kwargs) -> ConversationState:
    defaults = {
        "followup": False,
        "context_switch": False,
        "resolved_entities": [],
        "resolved_query": "",
        "conversation_confidence": 0.0,
        "current_topic": "general",
        "previous_topics": [],
        "conversation_summary": "",
        "recent_turns": [],
        "turn_count": 0,
    }
    defaults.update(kwargs)
    return ConversationState(**defaults)


class TestConversationRoute:
    def test_no_history_returns_zero(self):
        analysis = _make_analysis()
        conv = _make_conv(turn_count=0)
        score = _score_conversation_route(analysis, conv)
        assert score == 0.0

    def test_followup_boosts_score(self):
        analysis = _make_analysis()
        conv = _make_conv(
            followup=True,
            turn_count=3,
            conversation_confidence=0.5,
        )
        score = _score_conversation_route(analysis, conv)
        assert score >= 0.6

    def test_conversational_query_high_score(self):
        analysis = _make_analysis(query_type=QueryType.CONVERSATION)
        conv = _make_conv(turn_count=1, conversation_confidence=0.5)
        score = _score_conversation_route(analysis, conv)
        assert score >= 0.95

    def test_context_switch_penalizes(self):
        analysis = _make_analysis()
        conv = _make_conv(
            context_switch=True,
            turn_count=3,
            conversation_confidence=0.8,
        )
        score = _score_conversation_route(analysis, conv)
        assert score < 0.5


class TestDocumentRoute:
    def test_document_query_scores_high(self):
        analysis = _make_analysis(query_type=QueryType.DOCUMENT, requires_context=True)
        conv = _make_conv()
        score = _score_document_route(analysis, conv)
        assert score >= 0.7

    def test_conversational_query_scores_low(self):
        analysis = _make_analysis(query_type=QueryType.CONVERSATION, requires_context=False)
        conv = _make_conv()
        score = _score_document_route(analysis, conv)
        assert score < 0.3

    def test_complex_query_boosts(self):
        analysis = _make_analysis(
            query_type=QueryType.HYBRID,
            complexity_score=0.8,
            requires_context=True,
        )
        conv = _make_conv()
        score = _score_document_route(analysis, conv)
        assert score >= 0.8


class TestFreshDataRoute:
    def test_no_temporal_signals(self):
        analysis = _make_analysis(temporal_signals=[])
        score = _score_fresh_data_route(analysis)
        assert score == 0.0

    def test_temporal_signals_boost(self):
        analysis = _make_analysis(temporal_signals=["2026", "latest"])
        score = _score_fresh_data_route(analysis)
        assert score > 0.5

    def test_fresh_data_query_type(self):
        analysis = _make_analysis(
            query_type=QueryType.FRESH_DATA,
            temporal_signals=["today"],
        )
        score = _score_fresh_data_route(analysis)
        assert score >= 0.7
