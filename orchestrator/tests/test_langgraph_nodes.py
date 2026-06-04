"""
Tests for LangGraph Node wrappers inside steps.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from orchestrator.models.query_models import QueryAnalysis, QueryType
from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.routing_models import RouteScores, RetrievalBudget
from orchestrator.steps.step5_query_optimizer import OptimizedQuery
from orchestrator.models.context_models import ContextQuality, ContextPackage, RiskAssessment
from orchestrator.models.output_models import OrchestratorOutput

from orchestrator.steps.step1_query_understanding import step1_query_understanding_node
from orchestrator.steps.step2_conversation_intelligence import step2_conversation_intelligence_node
from orchestrator.steps.step3_route_scoring import step3_route_scoring_node
from orchestrator.steps.step4_retrieval_budget import step4_retrieval_budget_node
from orchestrator.steps.step5_query_optimizer import step5_query_optimization_node
from orchestrator.steps.step6_context_quality import step6_context_quality_node
from orchestrator.steps.step7_self_correction import step7_self_correction_node
from orchestrator.steps.step8_context_assembly import step8_context_assembly_node
from orchestrator.steps.step9_risk_control import step9_risk_control_node
from orchestrator.steps.step10_output import step10_output_node


@pytest.mark.asyncio
async def test_step1_node():
    mock_analysis = QueryAnalysis(
        intent="lookup",
        domain="general",
        confidence=0.9,
        ambiguity_score=0.1,
        entities=[],
        query_type=QueryType.DOCUMENT,
        objective="test query",
        complexity_score=0.2,
        requires_context=True,
        temporal_signals=[],
    )
    state = {
        "query": "What is photosynthesis?",
        "conversation_history": []
    }
    with patch("orchestrator.steps.step1_query_understanding.analyze_query", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_analysis
        result = await step1_query_understanding_node(state)
        
        mock_func.assert_called_once_with("What is photosynthesis?", [])
        assert result["query_analysis"] == mock_analysis
        assert "step1_query_understanding" in result["step_timings"]


@pytest.mark.asyncio
async def test_step2_node():
    mock_conv = ConversationState(
        followup=False,
        context_switch=False,
        resolved_entities=[],
        resolved_query="What is photosynthesis?",
        conversation_confidence=0.8,
        current_topic="biology",
        previous_topics=[],
        conversation_summary="",
        recent_turns=[],
        turn_count=0,
    )
    state = {
        "query": "What is photosynthesis?",
        "session_id": "test-session",
        "query_analysis": None
    }
    with patch("orchestrator.steps.step2_conversation_intelligence.process_conversation", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_conv
        result = await step2_conversation_intelligence_node(state)
        
        mock_func.assert_called_once_with("What is photosynthesis?", "test-session", None)
        assert result["conversation_state"] == mock_conv
        assert "step2_conversation_intelligence" in result["step_timings"]


@pytest.mark.asyncio
async def test_step3_node():
    mock_scores = RouteScores(
        conversation_score=0.1,
        memory_score=0.2,
        document_score=0.9,
        fresh_score=0.0,
    )
    state = {
        "query_analysis": None,
        "conversation_state": None,
    }
    with patch("orchestrator.steps.step3_route_scoring.score_routes", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_scores
        result = await step3_route_scoring_node(state)
        
        mock_func.assert_called_once_with(None, None)
        assert result["route_scores"] == mock_scores
        assert "step3_route_scoring" in result["step_timings"]


@pytest.mark.asyncio
async def test_step4_node():
    mock_budget = RetrievalBudget(
        retrieve=True,
        budget_level="medium",
        selected_routes=["document"],
        top_k=5,
        reasoning="test",
    )
    state = {
        "route_scores": None,
        "query_analysis": None,
    }
    with patch("orchestrator.steps.step4_retrieval_budget.allocate_budget", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_budget
        result = await step4_retrieval_budget_node(state)
        
        mock_func.assert_called_once_with(None, None)
        assert result["budget"] == mock_budget
        assert "step4_retrieval_budget" in result["step_timings"]


@pytest.mark.asyncio
async def test_step5_node():
    mock_opt = OptimizedQuery(
        primary_query="What is photosynthesis?",
        semantic_variants=[],
        original_query="What is photosynthesis?",
        optimization_applied=[],
    )
    state = {
        "query": "What is photosynthesis?",
        "conversation_state": None,
        "budget": None,
        "retry_count": 0,
    }
    with patch("orchestrator.steps.step5_query_optimizer.optimize_query", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_opt
        result = await step5_query_optimization_node(state)
        
        mock_func.assert_called_once_with("What is photosynthesis?", None, None, retry_count=0)
        assert result["optimized_query"] == mock_opt
        assert "step5_query_optimization_r0" in result["step_timings"]


@pytest.mark.asyncio
async def test_step6_node():
    mock_quality = ContextQuality(
        coverage_score=0.9,
        relevance_score=0.8,
        freshness_score=0.7,
        conflict_detected=False,
        duplicate_count=0,
        missing_aspects=[],
        evidence_confidence=0.85,
        verdict="sufficient",
    )
    state = {
        "query": "What is photosynthesis?",
        "query_analysis": None,
        "retrieved_chunks": [],
        "memories": [],
        "retry_count": 1,
    }
    with patch("orchestrator.steps.step6_context_quality.evaluate_quality", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_quality
        result = await step6_context_quality_node(state)
        
        mock_func.assert_called_once_with("What is photosynthesis?", None, [], [])
        assert result["quality"] == mock_quality
        assert "step6_quality_eval_r1" in result["step_timings"]


@pytest.mark.asyncio
async def test_step7_node():
    mock_budget = RetrievalBudget(
        retrieve=True,
        budget_level="medium",
        selected_routes=["document"],
        top_k=5,
        reasoning="test",
    )
    state = {
        "quality": None,
        "budget": mock_budget,
        "retry_count": 0,
    }
    with patch("orchestrator.steps.step7_self_correction.correct", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = (mock_budget, True, "query_rewrite")
        result = await step7_self_correction_node(state)
        
        mock_func.assert_called_once_with(None, mock_budget, 0)
        assert result["budget"] == mock_budget
        assert result["retry_count"] == 1
        assert "step7_self_correction_r0" in result["step_timings"]


@pytest.mark.asyncio
async def test_step8_node():
    mock_package = ContextPackage(
        conversation_context=[],
        user_context={},
        retrieved_evidence=[],
        memory_context=[],
        tool_outputs=[],
        total_tokens_estimate=0,
    )
    state = {
        "conversation_state": None,
        "memories": [],
        "retrieved_chunks": [],
        "quality": None,
        "tenant_id": "test-tenant",
    }
    with patch("orchestrator.steps.step8_context_assembly.assemble_context", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_package
        result = await step8_context_assembly_node(state)
        
        mock_func.assert_called_once_with(
            conversation_state=None,
            memories=[],
            retrieved_chunks=[],
            quality=None,
            session_metadata={"tenant_id": "test-tenant"},
        )
        assert result["context_package"] == mock_package
        assert "step8_context_assembly" in result["step_timings"]


@pytest.mark.asyncio
async def test_step9_node():
    mock_risk = RiskAssessment(
        safe=True,
        flags=[],
        pii_detected=[],
        injection_detected=False,
        blocked=False,
        reasoning="safe",
    )
    state = {
        "query": "What is photosynthesis?",
        "context_package": None,
        "tenant_id": "test-tenant",
    }
    with patch("orchestrator.steps.step9_risk_control.assess_risk", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_risk
        result = await step9_risk_control_node(state)
        
        mock_func.assert_called_once_with("What is photosynthesis?", None, "test-tenant")
        assert result["risk"] == mock_risk
        assert "step9_risk_control" in result["step_timings"]


@pytest.mark.asyncio
async def test_step10_node():
    mock_output = OrchestratorOutput(
        intent="lookup",
        topic="biology",
        entities=[],
        selected_routes=["document"],
        retrieval_required=True,
        budget_level="medium",
        evidence_confidence=0.8,
        context_package=ContextPackage(
            conversation_context=[],
            user_context={},
            retrieved_evidence=[],
            memory_context=[],
            tool_outputs=[],
            total_tokens_estimate=0,
        ),
        risk_flags=[],
        orchestrator_confidence=0.8,
        resolved_query="",
        needs_clarification=False,
        clarification_reason="",
        self_correction_count=0,
        metadata={},
    )
    state = {
        "query": "What is photosynthesis?",
        "query_analysis": None,
        "conversation_state": None,
        "route_scores": None,
        "budget": None,
        "quality": None,
        "memories": [],
        "context_package": None,
        "risk": None,
        "step_timings": {},
        "retry_count": 0,
        "needs_clarification": False,
        "clarification_reason": "",
    }
    with patch("orchestrator.steps.step10_output.format_output", new_callable=MagicMock) as mock_func, \
         patch("orchestrator.steps.step10_output.evaluate_quality", new_callable=AsyncMock) as mock_eval:
        mock_func.return_value = mock_output
        mock_eval.return_value = None
        result = await step10_output_node(state)
        
        assert result["output"] == mock_output
        assert "step10_output" in result["step_timings"]


from orchestrator.orchestrator import CognitiveOrchestrator

@pytest.mark.asyncio
async def test_cognitive_orchestrator_integration():
    orchestrator = CognitiveOrchestrator()
    with patch("orchestrator.orchestrator.conversation_store", new_callable=MagicMock) as mock_store:
        mock_store.get_history = AsyncMock(return_value=[])
        mock_store.add_turn = AsyncMock(return_value=None)
        
        mock_output = MagicMock(spec=OrchestratorOutput)
        mock_output.metadata = {}
        mock_output.orchestrator_confidence = 0.9
        mock_output.selected_routes = ["document"]
        
        with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = {
                "output": mock_output,
                "query_analysis": None,
                "conversation_state": None,
                "needs_clarification": False,
                "retry_count": 0,
            }
            
            res = await orchestrator.orchestrate("Hello", session_id="session-1")
            assert res == mock_output
            assert res.metadata["langgraph_execution"] is True

