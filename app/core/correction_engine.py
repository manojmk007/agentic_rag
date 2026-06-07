import os
import json
from litellm import acompletion
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.models.feedback import (
    FeedbackRequest,
    FeedbackSignal,
    IssueClassification,
    CorrectedAnswer,
)
from app.db.collections import Collections
from app.utils.id_generator import generate_signal_id
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()
os.environ["GEMINI_API_KEY"] = settings.gemini_api_key


async def classify_issue(
    feedback: FeedbackRequest,
    original_answer: str,
) -> IssueClassification:
    """
    Uses the LLM to automatically classify what kind of problem
    the user found with the answer.

    This drives what correction strategy to use:
      factual_error      → search MemPalace for verified facts
      completeness_gap   → ask LLM to expand the answer
      relevance_mismatch → flag for retrieval review
      outdated_content   → flag for fresh knowledge update
      clarity_issue      → ask LLM to simplify
    """
    # Build a compact classification prompt
    reason_hint = ""
    if feedback.thumbs_down_reason:
        reason_hint = f"User selected reason: {feedback.thumbs_down_reason.value}."
    if feedback.feedback_text:
        reason_hint += f" User wrote: {feedback.feedback_text}"

    prompt = f"""You are a feedback classifier. Classify the issue with this answer.

Original answer: {original_answer[:500]}

{reason_hint}

Respond with ONLY a JSON object, no other text:
{{"classification": "factual_error|completeness_gap|relevance_mismatch|outdated_content|clarity_issue|unknown", "reason": "one sentence explanation"}}"""

    try:
        response = await acompletion(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()

        # Parse the JSON response
        last_brace = raw.rfind("{")
        last_close = raw.rfind("}")
        if last_brace != -1 and last_close != -1:
            parsed = json.loads(raw[last_brace:last_close + 1])
            classification = parsed.get("classification", "unknown")
            try:
                result = IssueClassification(classification)
                logger.info(
                    "issue_classified",
                    response_id=feedback.response_id,
                    classification=result.value,
                    reason=parsed.get("reason", ""),
                )
                return result
            except ValueError:
                pass

    except Exception as e:
        logger.warning("issue_classification_failed", error=str(e))

    return IssueClassification.UNKNOWN


async def search_mempalace_for_correction(
    db: AsyncIOMotorDatabase,
    session_id: str,
    user_query_hint: str,
) -> str | None:
    """
    Searches the MemPalace signals collection for any previously
    verified corrections related to this session or similar queries.

    Returns the correction text if found, None otherwise.

    In a full MemPalace integration the upstream team would provide
    a search API. Here we query our own mempalace_signals collection
    for corrections marked as processed (verified by MemPalace).
    """
    try:
        cursor = db[Collections.MEMPALACE_SIGNALS].find(
            {
                "signal_type": {"$in": ["correction", "positive_with_correction"]},
                "processed": True,
                "session_id": session_id,
            }
        ).sort("created_at", -1).limit(3)

        docs = await cursor.to_list(length=3)

        if docs:
            # Return the most recent verified correction
            correction = docs[0].get("user_correction", "")
            if correction:
                logger.info(
                    "mempalace_correction_found",
                    session_id=session_id,
                    correction_preview=correction[:100],
                )
                return correction

    except Exception as e:
        logger.warning("mempalace_search_failed", error=str(e))

    return None


async def regenerate_answer(
    original_answer: str,
    user_query: str,
    issue_classification: IssueClassification,
    correction_context: str | None,
    user_correction: str | None,
) -> str:
    """
    Regenerates an improved answer using:
    1. The original answer as a baseline
    2. The issue classification to guide improvement strategy
    3. Any correction context from MemPalace
    4. Any direct correction provided by the user
    """
    # Build the correction strategy instruction
    strategy_map = {
        IssueClassification.FACTUAL_ERROR: (
            "The previous answer contained factual errors. "
            "Provide a corrected, accurate answer."
        ),
        IssueClassification.COMPLETENESS_GAP: (
            "The previous answer was incomplete. "
            "Provide a more thorough and complete answer."
        ),
        IssueClassification.RELEVANCE_MISMATCH: (
            "The previous answer was not relevant to the question. "
            "Focus specifically on what was asked."
        ),
        IssueClassification.OUTDATED_CONTENT: (
            "The previous answer contained outdated information. "
            "Provide the most current and accurate answer possible."
        ),
        IssueClassification.CLARITY_ISSUE: (
            "The previous answer was unclear or hard to understand. "
            "Provide a clearer, simpler explanation."
        ),
        IssueClassification.UNKNOWN: (
            "The previous answer was unsatisfactory. "
            "Provide an improved answer."
        ),
    }

    strategy = strategy_map.get(
        issue_classification,
        strategy_map[IssueClassification.UNKNOWN]
    )

    # Build the full regeneration prompt
    context_block = ""
    if correction_context:
        context_block += f"\n\nVerified correction from memory:\n{correction_context}"
    if user_correction:
        context_block += f"\n\nUser-provided correction:\n{user_correction}"

    prompt = f"""You are improving a previous answer based on user feedback.

Question: {user_query}

Previous answer: {original_answer}

Improvement strategy: {strategy}
{context_block}

Provide an improved answer. Be concise and accurate. Do not reference the previous answer."""

    try:
        response = await acompletion(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=settings.llm_max_tokens,
            temperature=0.2,
        )
        improved = response.choices[0].message.content.strip()
        logger.info(
            "answer_regenerated",
            issue=issue_classification.value,
            original_length=len(original_answer),
            new_length=len(improved),
        )
        return improved

    except Exception as e:
        logger.error("regeneration_failed", error=str(e))
        # Degrade gracefully — return original answer if regeneration fails
        return original_answer


async def run_correction_flow(
    feedback: FeedbackRequest,
    signal: FeedbackSignal,
    original_answer: str,
    user_query: str,
    db: AsyncIOMotorDatabase,
) -> CorrectedAnswer | None:
    """
    Full correction pipeline triggered on thumbs down.

    1. Classify the issue
    2. Search MemPalace for existing corrections
    3. Regenerate an improved answer
    4. Return a CorrectedAnswer ready for storage

    Returns None if the correction flow cannot run
    (e.g. no original answer available).
    """
    if not original_answer:
        return None

    logger.info(
        "correction_flow_started",
        response_id=feedback.response_id,
        session_id=feedback.session_id,
    )

    # Step 1 — Classify the issue
    classification = await classify_issue(feedback, original_answer)

    # Step 2 — Search MemPalace for existing verified corrections
    memory_correction = await search_mempalace_for_correction(
        db=db,
        session_id=feedback.session_id,
        user_query_hint=user_query[:200],
    )

    # Step 3 — Determine correction source
    if memory_correction or feedback.user_correction:
        correction_source = "memory" if memory_correction else "user_provided"
    else:
        correction_source = "regenerated"

    # Step 4 — Regenerate
    corrected = await regenerate_answer(
        original_answer=original_answer,
        user_query=user_query,
        issue_classification=classification,
        correction_context=memory_correction,
        user_correction=feedback.user_correction,
    )

    return CorrectedAnswer(
        correction_id=generate_signal_id(),
        response_id=feedback.response_id,
        signal_id=signal.signal_id,
        session_id=feedback.session_id,
        original_answer=original_answer,
        corrected_answer=corrected,
        issue_classification=classification,
        correction_source=correction_source,
        user_correction_used=feedback.user_correction,
        received_positive_feedback=False,
    )