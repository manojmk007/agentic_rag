"""
orchestrator/orchestrator.py
==============================
Central Cognitive Orchestrator — the main decision engine.

Coordinates all steps using a LangGraph StateGraph:
  1. Query Understanding
  2. Conversation Intelligence
  3. Route Scoring
  4. Retrieval Budget
  5. Memory Retrieval (if applicable)
  6-8. Self-Correction Loop (Optimize → Retrieve → Evaluate → Correct)
  9. Context Assembly
  10. Risk Control
  11. Final Output

The orchestrator produces structured context packages for downstream answer generation.
"""

import time
import uuid
from typing import Optional, Literal

from langgraph.graph import StateGraph, START, END

from orchestrator.graph_state import OrchestratorState
from orchestrator.models.output_models import OrchestratorOutput
from orchestrator.models.context_models import RetrievedChunk

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

import asyncio
from orchestrator.services.conversation_store import conversation_store
from orchestrator.services.memory_store import memory_store
from orchestrator.services.retrieval_interface import RetrievalInterface, MockRetriever
from orchestrator.services.fresh_data_retriever import FreshDataRetriever
from orchestrator.services.observability import (
    get_logger,
    set_request_id,
    set_session_id,
    metrics,
    track_latency,
)
from orchestrator.config.settings import settings

logger = get_logger(__name__)


# ── LangGraph Node Functions ──────────────────────────────────────────


async def node_memory_retrieval(state: OrchestratorState) -> dict:
    # Memory retrieval has been parallelized inside the unified retrieval node.
    # We return a pass-through immediately to keep graph edges intact.
    return {"retry_count": state["retry_count"]}


def create_retrieval_node(retriever: RetrievalInterface, fresh_retriever: RetrievalInterface):
    """Factory to create the retrieval node with the injected retrievers."""
    async def node_retrieval(state: OrchestratorState) -> dict:
        t0 = time.perf_counter()
        budget = state["budget"]
        optimized = state["optimized_query"]
        retry_count = state["retry_count"]
        
        retrieved_chunks = []
        memories = []
        
        # Determine active retrieval sub-pipelines
        run_doc = "document" in budget.selected_routes
        run_fresh = "fresh" in budget.selected_routes
        run_mem = "memory" in budget.selected_routes
        
        # Fallback to document search if budget says retrieve but no routes are selected
        if not run_doc and not run_fresh and not run_mem:
            run_doc = True
            
        tasks = []
        
        if run_doc:
            async def search_doc():
                try:
                    raw = await retriever.search(
                        query=optimized.primary_query,
                        top_k=budget.top_k,
                        filters=state["filters"],
                    )
                    return "doc", [{"id": c.id, "text": c.text, "score": c.score, "source": c.source, "metadata": c.metadata} for c in raw]
                except Exception as e:
                    logger.error("mongodb_retrieval_failed_in_node", error=str(e))
                    return "doc", []
            tasks.append(search_doc())
            
        if run_fresh:
            async def search_fresh():
                try:
                    raw = await fresh_retriever.search(
                        query=optimized.primary_query,
                        top_k=5, # Limit fresh web search results to top 5
                        filters=state["filters"],
                    )
                    return "fresh", [{"id": c.id, "text": c.text, "score": c.score, "source": c.source, "metadata": c.metadata} for c in raw]
                except Exception as e:
                    logger.error("fresh_retrieval_failed_in_node", error=str(e))
                    return "fresh", []
            tasks.append(search_fresh())

        if run_mem:
            async def search_mem():
                try:
                    search_query = state["conversation_state"].resolved_query or state["query"]
                    raw = await memory_store.search_memories(search_query)
                    return "mem", raw
                except Exception as e:
                    logger.error("memory_retrieval_failed_in_parallel_node", error=str(e))
                    return "mem", []
            tasks.append(search_mem())
            
        if tasks:
            results = await asyncio.gather(*tasks)
            for source, res in results:
                if source == "mem":
                    memories = res
                else:
                    retrieved_chunks.extend(res)
                
        # Multi-query variant search for high budgets (Document only)
        if run_doc and optimized.semantic_variants and budget.budget_level in ("medium", "high"):
            # Check if we already hit a database miss to skip variant queries
            is_db_miss = any(c.get("metadata", {}).get("db_miss") for c in retrieved_chunks)
            if not is_db_miss:
                variant_tasks = []
                for variant in optimized.semantic_variants[:2]:
                    async def search_var(v=variant):
                        try:
                          raw = await retriever.search(
                              query=v,
                              top_k=max(budget.top_k // 3, 10),
                              filters=state["filters"],
                          )
                          return [{"id": c.id, "text": c.text, "score": c.score, "source": c.source, "metadata": c.metadata} for c in raw]
                        except Exception:
                          return []
                    variant_tasks.append(search_var())
                if variant_tasks:
                    var_results = await asyncio.gather(*variant_tasks)
                    for res in var_results:
                        retrieved_chunks.extend(res)
                    
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        
        # Check early abort on database miss
        is_db_miss = any(c.get("metadata", {}).get("db_miss") for c in retrieved_chunks)
        
        updates = {
            "retrieved_chunks": retrieved_chunks,
            "memories": memories,
            "step_timings": {f"retrieval_r{retry_count}": elapsed}
        }
        
        if is_db_miss:
            updates["needs_clarification"] = True
            updates["clarification_reason"] = "System Notification: No documents in storage match the query topic."
            
        return updates

    return node_retrieval





# ── Conditional Edges ───────────────────────────────────────────────

def route_after_budget(state: OrchestratorState) -> Literal["query_optimization", "context_assembly"]:
    """Decide whether to perform retrieval or skip to assembly."""
    if state["budget"].retrieve:
        return "query_optimization"
    return "context_assembly"

def route_after_correction(state: OrchestratorState) -> Literal["query_optimization", "context_assembly"]:
    """Decide whether to loop back for retry or move to assembly."""
    # We set retry_count + 1 in the self_correction node if should_retry is True
    # However, to avoid maintaining complex state, we can just check if retry_count > previous
    # Alternatively, just check if needs_clarification is False AND quality is insufficient?
    # Wait, the node itself bumps retry_count if it wants to loop.
    # Let's add a "should_retry" flag to state? Or just use a simple check:
    
    # If quality is sufficient or retries exhausted, move to assembly
    # Our node_self_correction only increases retry_count if it wants to retry.
    # But wait, we don't know the PREVIOUS retry count cleanly unless we pass a flag.
    # Let's just evaluate quality and max retries here instead of inside the node?
    pass

# We need a cleaner way to route after correction. 
# Let's use a standard LangGraph state update pattern:
def route_after_correction(state: OrchestratorState) -> Literal["query_optimization", "context_assembly"]:
    # The self_correction node increases the top_k or budget if it wants to retry.
    # If we haven't reached max retries AND quality is not sufficient, it should retry.
    # Let's check the verdict directly.
    quality = state["quality"]
    if quality.verdict == "sufficient" or state["retry_count"] > settings.max_self_correction_retries:
        return "context_assembly"
    
    # If we're at or above max retries, the correction node already flagged needs_clarification.
    if state["needs_clarification"]:
        return "context_assembly"
        
    # Otherwise we retry
    return "query_optimization"


# ── Orchestrator Class ──────────────────────────────────────────────

class CognitiveOrchestrator:
    """
    Enterprise Cognitive Orchestrator powered by LangGraph.
    """

    def __init__(self, retriever: Optional[RetrievalInterface] = None):
        self._retriever = retriever or MockRetriever()
        self._fresh_retriever = FreshDataRetriever()
        self._graph = self._build_graph()

    def set_retriever(self, retriever: RetrievalInterface) -> None:
        """Swap the retrieval backend at runtime and rebuild graph."""
        self._retriever = retriever
        self._graph = self._build_graph()

    def _build_graph(self):
        """Construct the LangGraph StateGraph pipeline."""
        builder = StateGraph(OrchestratorState)
        
        # Add Nodes
        builder.add_node("query_understanding", step1_query_understanding_node)
        builder.add_node("conversation_intelligence", step2_conversation_intelligence_node)
        builder.add_node("route_scoring", step3_route_scoring_node)
        builder.add_node("retrieval_budget", step4_retrieval_budget_node)
        builder.add_node("memory_retrieval", node_memory_retrieval)
        builder.add_node("query_optimization", step5_query_optimization_node)
        builder.add_node("retrieval", create_retrieval_node(self._retriever, self._fresh_retriever))
        builder.add_node("context_quality", step6_context_quality_node)
        builder.add_node("self_correction", step7_self_correction_node)
        builder.add_node("context_assembly", step8_context_assembly_node)
        builder.add_node("risk_control", step9_risk_control_node)
        builder.add_node("format_output", step10_output_node)
        
        # Add Edges (linear sequence)
        builder.add_edge(START, "query_understanding")
        builder.add_edge("query_understanding", "conversation_intelligence")
        builder.add_edge("conversation_intelligence", "route_scoring")
        builder.add_edge("route_scoring", "retrieval_budget")
        builder.add_edge("retrieval_budget", "memory_retrieval")
        
        # Conditional Edge after memory_retrieval
        builder.add_conditional_edges(
            "memory_retrieval",
            route_after_budget,
            {
                "query_optimization": "query_optimization",
                "context_assembly": "context_assembly"
            }
        )
        
        # Retrieval Loop Sequence
        builder.add_edge("query_optimization", "retrieval")
        builder.add_edge("retrieval", "context_quality")
        builder.add_edge("context_quality", "self_correction")
        
        # Conditional Edge after self_correction (The Loop)
        builder.add_conditional_edges(
            "self_correction",
            route_after_correction,
            {
                "query_optimization": "query_optimization",
                "context_assembly": "context_assembly"
            }
        )
        
        # Finalization Sequence
        builder.add_edge("context_assembly", "risk_control")
        builder.add_edge("risk_control", "format_output")
        builder.add_edge("format_output", END)
        
        return builder.compile()

    @track_latency("orchestrate_total")
    async def orchestrate(
        self,
        query: str,
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> OrchestratorOutput:
        """Run the full LangGraph orchestration pipeline."""
        session_id = session_id or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        set_request_id(request_id)
        set_session_id(session_id)

        total_start = time.perf_counter()
        logger.info("orchestration_started", query=query[:80], session_id=session_id)

        # 1. Fetch conversation history outside the graph (as requested)
        conversation_history = await conversation_store.get_history(session_id, limit=5)
        
        # 2. Initialize State
        initial_state = {
            "query": query,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "filters": filters,
            "conversation_history": conversation_history,
            "retrieved_chunks": [],
            "memories": [],
            "retry_count": 0,
            "needs_clarification": False,
            "clarification_reason": "",
            "step_timings": {},
        }
        
        # 3. Invoke LangGraph
        final_state = await self._graph.ainvoke(initial_state)
        
        # 4. Finalize
        output: OrchestratorOutput = final_state["output"]
        total_ms = round((time.perf_counter() - total_start) * 1000, 2)
        output.metadata["total_latency_ms"] = total_ms
        output.metadata["request_id"] = request_id
        output.metadata["session_id"] = session_id
        output.metadata["langgraph_execution"] = True

        # Save conversation turn
        try:
            await conversation_store.add_turn(
                session_id=session_id,
                role="user",
                content=query,
                entities=final_state["query_analysis"].entities if final_state.get("query_analysis") else [],
                topic=final_state["conversation_state"].current_topic if final_state.get("conversation_state") else "",
            )
        except Exception as e:
            logger.warning("conversation_save_failed", error=str(e))

        # Metrics
        metrics.increment("orchestrations_completed")
        if final_state["needs_clarification"]:
            metrics.increment("clarification_requests")
        if final_state["retry_count"] > 0:
            metrics.increment("self_corrections_triggered")

        logger.info(
            "orchestration_completed",
            total_ms=total_ms,
            confidence=output.orchestrator_confidence,
            routes=output.selected_routes,
            corrections=final_state["retry_count"],
        )

        return output
