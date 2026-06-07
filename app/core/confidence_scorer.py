from app.models.context import AssembledContext
from app.models.response import LLMResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


def score_citation_coverage(llm_response: LLMResponse, context: AssembledContext) -> float:
    """
    Measures what fraction of the provided source documents were actually
    cited by the LLM in its answer.

    A low score means the LLM ignored most of the context — possible
    hallucination risk or irrelevant retrieval.

    Score = cited_sources / total_provided_sources
    """
    total_sources = len(context.source_documents)
    if total_sources == 0:
        # No sources provided — citation coverage is not applicable
        return 1.0

    cited = len(llm_response.source_ids)
    score = min(cited / total_sources, 1.0)

    logger.debug(
        "citation_coverage_scored",
        response_id=llm_response.response_id,
        cited=cited,
        total=total_sources,
        score=score,
    )
    return round(score, 4)


def score_retrieval_relevance(llm_response: LLMResponse, context: AssembledContext) -> float:
    """
    Measures the average retrieval score of the documents the LLM actually cited.

    If the LLM cited high-scoring documents, relevance is high.
    If it cited low-scoring documents or none, relevance is low.

    This tells you whether the retrieval pipeline sent useful documents.
    """
    if not llm_response.source_ids or not context.source_documents:
        return 0.0

    # Build a lookup of source_id → retrieval score
    score_map = {doc.source_id: doc.score for doc in context.source_documents}

    cited_scores = [
        score_map[sid]
        for sid in llm_response.source_ids
        if sid in score_map
    ]

    if not cited_scores:
        return 0.0

    avg_score = sum(cited_scores) / len(cited_scores)

    logger.debug(
        "retrieval_relevance_scored",
        response_id=llm_response.response_id,
        cited_ids=llm_response.source_ids,
        avg_score=avg_score,
    )
    return round(avg_score, 4)


def score_answer_length(llm_response: LLMResponse) -> float:
    """
    Penalises extremely short answers (likely low quality)
    and very long answers (might be unfocused).

    Optimal range: 50-500 words maps to score 1.0
    Below 20 words: score 0.3
    Above 800 words: score 0.7
    """
    word_count = len(llm_response.raw_answer.split())

    if word_count < 20:
        return 0.3
    elif word_count < 50:
        # Linear ramp from 0.3 to 1.0 between 20-50 words
        return 0.3 + (word_count - 20) / 30 * 0.7
    elif word_count <= 500:
        return 1.0
    elif word_count <= 800:
        # Linear ramp from 1.0 down to 0.7 between 500-800 words
        return 1.0 - (word_count - 500) / 300 * 0.3
    else:
        return 0.7