"""
Tests for Step 7 — Self-Correction.
"""

import pytest
from orchestrator.models.context_models import ContextQuality
from orchestrator.models.routing_models import RetrievalBudget
from orchestrator.steps.step7_self_correction import correct


def _make_quality(verdict: str, confidence: float = 0.5) -> ContextQuality:
    return ContextQuality(
        coverage_score=0.5,
        relevance_score=0.5,
        freshness_score=0.7,
        conflict_detected=False,
        duplicate_count=0,
        missing_aspects=[],
        evidence_confidence=confidence,
        verdict=verdict,
    )


def _make_budget(level: str = "medium", top_k: int = 50) -> RetrievalBudget:
    return RetrievalBudget(
        retrieve=True,
        budget_level=level,
        selected_routes=["document"],
        top_k=top_k,
        reasoning="test",
    )


@pytest.mark.asyncio
class TestSelfCorrection:
    async def test_sufficient_quality_no_retry(self):
        quality = _make_quality("sufficient", 0.8)
        budget = _make_budget()
        new_budget, should_retry, strategy = await correct(quality, budget, 0)
        assert should_retry is False
        assert strategy == "quality_sufficient"

    async def test_insufficient_triggers_retry_0(self):
        quality = _make_quality("insufficient", 0.2)
        budget = _make_budget("medium", 50)
        new_budget, should_retry, strategy = await correct(quality, budget, 0)
        assert should_retry is True
        assert strategy == "query_rewrite"
        assert new_budget.top_k > budget.top_k

    async def test_insufficient_triggers_retry_1(self):
        quality = _make_quality("insufficient", 0.3)
        budget = _make_budget("medium", 75)
        new_budget, should_retry, strategy = await correct(quality, budget, 1)
        assert should_retry is True
        assert strategy == "query_expansion"
        assert new_budget.budget_level == "high"

    async def test_retries_exhausted_at_max(self):
        quality = _make_quality("insufficient", 0.2)
        budget = _make_budget("high", 100)
        new_budget, should_retry, strategy = await correct(quality, budget, 2, max_retries=2)
        assert should_retry is False
        assert strategy == "retries_exhausted_ask_clarification"

    async def test_marginal_triggers_retry(self):
        quality = _make_quality("marginal", 0.4)
        budget = _make_budget()
        new_budget, should_retry, strategy = await correct(quality, budget, 0)
        assert should_retry is True
