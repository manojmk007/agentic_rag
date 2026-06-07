from app.config import get_settings
from app.models.context import AssembledContext
from app.models.response import LLMResponse
from app.models.validation import ValidationResult
from app.core.confidence_scorer import (
    score_citation_coverage,
    score_retrieval_relevance,
    score_answer_length,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Weights must sum to 1.0
# Tweak these as your system matures and you collect feedback data
SCORE_WEIGHTS = {
    "confidence": 0.45,      # LLM self-reported confidence carries most weight
    "citation_coverage": 0.30,  # Were sources actually used?
    "relevance": 0.25,       # Were the right sources cited?
}

# Answers shorter than this get flagged even if they pass the threshold
MIN_ANSWER_WORDS = 10

# Phrases that indicate the LLM couldn't answer — we flag but still pass these
UNCERTAINTY_PHRASES = [
    "i don't have enough information",
    "i cannot answer",
    "not enough context",
    "i don't know",
    "no information available",
]


def _check_uncertainty_phrases(answer: str) -> bool:
    """Returns True if the answer contains an uncertainty phrase."""
    lower = answer.lower()
    return any(phrase in lower for phrase in UNCERTAINTY_PHRASES)


def validate_response(
    llm_response: LLMResponse,
    context: AssembledContext,
) -> ValidationResult:
    """
    Runs all validation checks and produces a ValidationResult.

    Does NOT raise exceptions — instead sets passed=False with reasons.
    The caller (graph node) decides what to do with a failed validation.
    """
    failure_reasons = []
    flagged = False

    # ── Individual scores ─────────────────────────────────────────────────────
    confidence = llm_response.confidence_score
    citation_coverage = score_citation_coverage(llm_response, context)
    relevance = score_retrieval_relevance(llm_response, context)
    length_score = score_answer_length(llm_response)

    # ── Weighted overall score ────────────────────────────────────────────────
    # Length score acts as a multiplier — a good answer must be a reasonable length
# Length score blended in at 10% weight — soft penalty, not a multiplier
    length_weight = 0.10
    base_weight = 1.0 - length_weight

    raw_overall = (
        confidence * SCORE_WEIGHTS["confidence"] * base_weight
        + citation_coverage * SCORE_WEIGHTS["citation_coverage"] * base_weight
        + relevance * SCORE_WEIGHTS["relevance"] * base_weight
        + length_score * length_weight
    )
    overall_score = round(raw_overall, 4)

    # ── Threshold checks ──────────────────────────────────────────────────────
    if confidence < settings.confidence_threshold:
        failure_reasons.append(
            f"Confidence {confidence:.2f} below threshold {settings.confidence_threshold}"
        )

    if citation_coverage < settings.citation_coverage_threshold:
        failure_reasons.append(
            f"Citation coverage {citation_coverage:.2f} below threshold "
            f"{settings.citation_coverage_threshold}"
        )

    if relevance < settings.relevance_threshold and context.source_documents:
        failure_reasons.append(
            f"Retrieval relevance {relevance:.2f} below threshold "
            f"{settings.relevance_threshold}"
        )

    # ── Uncertainty check ─────────────────────────────────────────────────────
    if _check_uncertainty_phrases(llm_response.raw_answer):
        flagged = True
        logger.warning(
            "answer_contains_uncertainty",
            response_id=llm_response.response_id,
        )

    # ── Length check ──────────────────────────────────────────────────────────
    word_count = len(llm_response.raw_answer.split())
    if word_count < MIN_ANSWER_WORDS:
        failure_reasons.append(f"Answer too short: {word_count} words")
        flagged = True

    passed = len(failure_reasons) == 0

    result = ValidationResult(
        response_id=llm_response.response_id,
        confidence_score=round(confidence, 4),
        citation_coverage_score=round(citation_coverage, 4),
        relevance_score=round(relevance, 4),
        overall_score=overall_score,
        passed=passed,
        failure_reasons=failure_reasons,
        flagged_for_review=flagged,
    )

    logger.info(
        "validation_complete",
        response_id=llm_response.response_id,
        passed=passed,
        overall_score=overall_score,
        confidence=confidence,
        citation_coverage=citation_coverage,
        relevance=relevance,
        failure_reasons=failure_reasons,
    )

    return result