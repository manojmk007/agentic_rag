"""
Tests for Step 4 — Retrieval Budget.
"""

import pytest
from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.routing_models import RouteScores
from orchestrator.steps.step4_retrieval_budget import allocate_budget


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


@pytest.mark.asyncio
class TestBudgetAllocation:
    async def test_high_conversation_skips_retrieval(self):
        scores = RouteScores(
            conversation_score=0.95,
            memory_score=0.3,
            document_score=0.4,
            fresh_score=0.0,
        )
        budget = await allocate_budget(scores, _make_analysis())
        assert budget.retrieve is False
        assert budget.budget_level == "skip"
        assert "conversation" in budget.selected_routes

    async def test_high_memory_low_budget(self):
        scores = RouteScores(
            conversation_score=0.3,
            memory_score=0.95,
            document_score=0.2,
            fresh_score=0.0,
        )
        budget = await allocate_budget(scores, _make_analysis())
        assert budget.retrieve is True
        assert budget.budget_level == "low"
        assert "memory" in budget.selected_routes

    async def test_moderate_scores_medium_budget(self):
        scores = RouteScores(
            conversation_score=0.4,
            memory_score=0.5,
            document_score=0.7,
            fresh_score=0.1,
        )
        budget = await allocate_budget(scores, _make_analysis())
        assert budget.retrieve is True
        assert budget.budget_level == "medium"
        assert "document" in budget.selected_routes

    async def test_low_scores_high_budget(self):
        scores = RouteScores(
            conversation_score=0.1,
            memory_score=0.2,
            document_score=0.3,
            fresh_score=0.0,
        )
        budget = await allocate_budget(scores, _make_analysis())
        assert budget.retrieve is True
        assert budget.budget_level == "high"

    async def test_complex_query_gets_medium_minimum(self):
        scores = RouteScores(
            conversation_score=0.5,
            memory_score=0.5,
            document_score=0.6,
            fresh_score=0.0,
        )
        analysis = _make_analysis(complexity_score=0.7)
        budget = await allocate_budget(scores, analysis)
        assert budget.budget_level in ("medium", "high")
