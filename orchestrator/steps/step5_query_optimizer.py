"""
orchestrator/steps/step5_query_optimizer.py
=============================================
Step 5 — Query Optimization Engine.

Before retrieval:
  - Inject resolved coreferences
  - Expand abbreviations/acronyms
  - LLM-powered query rewriting for retrieval
  - Generate 2-3 semantic variants (for multi-query retrieval)
  - Scope broadening on retries
"""

from dataclasses import dataclass, field

from orchestrator.models.conversation_models import ConversationState
from orchestrator.models.routing_models import RetrievalBudget
from orchestrator.services.llm_service import llm_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


@dataclass
class OptimizedQuery:
    """Result of query optimization."""
    primary_query: str          # Main optimized query for retrieval
    semantic_variants: list[str] = field(default_factory=list)  # Alternate phrasings
    original_query: str = ""    # Original unchanged query
    optimization_applied: list[str] = field(default_factory=list)  # What was done


# ── Common Abbreviations ─────────────────────────────────────

_ABBREVIATIONS = {
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "dl": "deep learning",
    "llm": "large language model",
    "api": "application programming interface",
    "db": "database",
    "ui": "user interface",
    "ux": "user experience",
    "ci/cd": "continuous integration and continuous deployment",
    "k8s": "kubernetes",
    "rag": "retrieval augmented generation",
    "rrf": "reciprocal rank fusion",
    "pii": "personally identifiable information",
    "sso": "single sign-on",
    "oauth": "open authorization",
    "jwt": "json web token",
    "sql": "structured query language",
    "nosql": "non-relational database",
}


def _expand_abbreviations(query: str) -> tuple[str, bool]:
    """Expand known abbreviations in the query."""
    expanded = query
    changed = False
    words = query.lower().split()
    for abbr, full in _ABBREVIATIONS.items():
        if abbr in words:
            # Only expand if it's a standalone word
            import re
            pattern = rf"\b{re.escape(abbr)}\b"
            new_expanded = re.sub(pattern, f"{abbr} ({full})", expanded, flags=re.IGNORECASE)
            if new_expanded != expanded:
                expanded = new_expanded
                changed = True
    return expanded, changed


@track_latency("step5_query_optimization")
async def optimize_query(
    original_query: str,
    conversation_state: ConversationState,
    budget: RetrievalBudget,
    retry_count: int = 0,
) -> OptimizedQuery:
    """
    Step 5: Optimize the query for maximum retrieval accuracy.

    On retry_count > 0, progressively broadens the search scope.
    """
    optimizations: list[str] = []
    working_query = original_query

    # ── Skip optimization if no retrieval needed ─────────────
    if not budget.retrieve:
        return OptimizedQuery(
            primary_query=original_query,
            original_query=original_query,
            optimization_applied=["skipped_no_retrieval"],
        )

    # ── Step 5a: Inject resolved coreferences ────────────────
    if conversation_state.resolved_query != original_query and conversation_state.resolved_query:
        working_query = conversation_state.resolved_query
        optimizations.append("coreference_resolved")

    # ── Step 5b: Expand abbreviations ────────────────────────
    expanded, did_expand = _expand_abbreviations(working_query)
    if did_expand:
        working_query = expanded
        optimizations.append("abbreviations_expanded")

    # ── Step 5c & 5d: Consolidated Rewrite & Variant Generation ──
    working_query, variants = await _llm_optimize_and_variants(working_query, retry_count, original_query)
    
    if working_query != original_query:
        if retry_count == 0:
            optimizations.append("llm_rewritten")
        elif retry_count == 1:
            optimizations.append("llm_rewritten_broader")
        else:
            optimizations.append("llm_rewritten_expanded")
            
    if variants:
        optimizations.append(f"variants_generated({len(variants)})")

    result = OptimizedQuery(
        primary_query=working_query,
        semantic_variants=variants,
        original_query=original_query,
        optimization_applied=optimizations,
    )

    logger.info(
        "query_optimized",
        original=original_query[:50],
        optimized=working_query[:50],
        variants=len(variants),
        retry=retry_count,
        steps=optimizations,
    )

    return result


async def _llm_optimize_and_variants(
    query: str, retry_count: int, original: str = ""
) -> tuple[str, list[str]]:
    """Optimizes the query and generates semantic variants in a single JSON LLM call."""
    num_variants = 2 + retry_count
    
    if retry_count == 0:
        prompt = (
            f"Optimize this user query for document search.\n"
            f"Provide:\n"
            f"1. primary_query: A concise, specific search query optimized for retrieval.\n"
            f"2. variants: A list of {num_variants} semantically different phrasings of the query.\n\n"
            f"Query: \"{query}\"\n\n"
            f"Respond with JSON format only:\n"
            f'{{"primary_query": "...", "variants": ["...", "..."]}}'
        )
    elif retry_count == 1:
        prompt = (
            f"The search for the query failed. Broaden the query to find related information.\n"
            f"Provide:\n"
            f"1. primary_query: A broader, more general version of the query (remove specific constraints).\n"
            f"2. variants: A list of {num_variants} broader related search queries.\n\n"
            f"Query: \"{query}\"\n\n"
            f"Respond with JSON format only:\n"
            f'{{"primary_query": "...", "variants": ["...", "..."]}}'
        )
    else:
        prompt = (
            f"The search failed repeatedly. Expand the query scope maximally focusing only on the main subject.\n"
            f"Provide:\n"
            f"1. primary_query: A very broad search query.\n"
            f"2. variants: A list of {num_variants} general related search queries.\n\n"
            f"Original Query: \"{original}\"\n"
            f"Previous Query: \"{query}\"\n\n"
            f"Respond with JSON format only:\n"
            f'{{"primary_query": "...", "variants": ["...", "..."]}}'
        )

    try:
        res = await llm_service.generate_json(prompt, is_complex=False)
        primary = res.get("primary_query", query).strip().strip('"\'')
        variants = res.get("variants", [])
        if not isinstance(variants, list):
            variants = []
        variants = [str(v).strip() for v in variants[:num_variants] if v]
        return primary, variants
    except Exception as e:
        logger.warning("llm_optimize_and_variants_failed", error=str(e))
        return query, []


import time


async def step5_query_optimization_node(state: dict) -> dict:
    """LangGraph node for Step 5: Query Optimization."""
    t0 = time.perf_counter()
    optimized = await optimize_query(
        state["query"],
        state["conversation_state"],
        state["budget"],
        retry_count=state["retry_count"],
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "optimized_query": optimized,
        "step_timings": {f"step5_query_optimization_r{state['retry_count']}": elapsed}
    }


