from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dependencies import get_db
from app.models.feedback import FeedbackRequest, FeedbackType, ReasonUpdateRequest
from app.core.feedback_processor import process_feedback
from app.core.confidence_tracker import ConfidenceTracker
from app.core.correction_engine import run_correction_flow
from app.db.repositories.feedback_repo import FeedbackRepository
from app.db.repositories.mempalace_repo import MemPalaceRepository
from app.db.repositories.response_repo import ResponseRepository
from app.db.repositories.correction_repo import CorrectionRepository
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/feedback", status_code=201)
async def submit_feedback(
    feedback: FeedbackRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Submit user feedback for a generated response.

    THUMBS UP flow:
      1. Store positive feedback signal
      2. Increment positive_count, recalculate confidence_score
      3. Write reinforcement signal to MemPalace
      4. If previous corrections exist, mark them successful

    THUMBS DOWN flow:
      1. Store negative feedback signal
      2. Increment negative_count, recalculate confidence_score
      3. Auto-classify the issue
      4. Search MemPalace for existing corrections
      5. Regenerate improved answer
      6. Store original + corrected answer
      7. Write negative signal to MemPalace

    Returns the signal_id and corrected_answer (if generated).
    """
    response_repo = ResponseRepository(db)
    feedback_repo = FeedbackRepository(db)
    mempalace_repo = MemPalaceRepository(db)
    confidence_tracker = ConfidenceTracker(db)
    correction_repo = CorrectionRepository(db)

    # Verify the response exists and get its data
    stored_response = await response_repo.get_response(feedback.response_id)
    source_ids = stored_response.get("source_ids", [])
    original_answer = stored_response.get("raw_answer", "")
    # We store the user query in metadata during generation
    user_query = stored_response.get("metadata", {}).get("user_query", "")

    # Process feedback into signal + MemPalace entry
    signal, mempalace_entry = process_feedback(feedback, source_ids)

    # Persist the feedback event
    await feedback_repo.save_feedback(feedback, signal)

    # Update confidence score atomically
    confidence = await confidence_tracker.record_feedback(
        response_id=feedback.response_id,
        feedback_type=feedback.feedback_type,
    )

    # Write signal to MemPalace collection
    await mempalace_repo.write_signal(mempalace_entry)

    response_payload = {
        "status": "accepted",
        "signal_id": signal.signal_id,
        "response_id": feedback.response_id,
        "signal_type": mempalace_entry.signal_type,
        "signal_strength": signal.signal_strength,
        "confidence_score": confidence.confidence_score,
        "positive_count": confidence.positive_count,
        "negative_count": confidence.negative_count,
        "corrected_answer": None,
        "correction_id": None,
    }

    # ── THUMBS UP: mark any existing corrections as successful ────────────────
    if feedback.feedback_type == FeedbackType.THUMBS_UP:
        try:
            await correction_repo.mark_correction_successful(
                feedback.response_id
            )
        except Exception as e:
            # Non-critical — log but don't fail the request
            logger.warning(
                "mark_correction_successful_failed",
                error=str(e),
            )

    # ── THUMBS DOWN: run the correction engine ────────────────────────────────
    if feedback.feedback_type == FeedbackType.THUMBS_DOWN:
        try:
            correction = await run_correction_flow(
                feedback=feedback,
                signal=signal,
                original_answer=original_answer,
                user_query=user_query,
                db=db,
            )
            if correction:
                await correction_repo.save_correction(correction)
                response_payload["corrected_answer"] = correction.corrected_answer
                response_payload["correction_id"] = correction.correction_id

                logger.info(
                    "correction_flow_completed",
                    correction_id=correction.correction_id,
                    source=correction.correction_source,
                    classification=correction.issue_classification.value,
                )
        except Exception as e:
            # Correction failure must NOT fail the feedback acceptance
            logger.error("correction_flow_failed", error=str(e))

    logger.info(
        "feedback_accepted",
        signal_id=signal.signal_id,
        response_id=feedback.response_id,
        feedback_type=feedback.feedback_type.value,
        confidence_score=confidence.confidence_score,
    )

    return response_payload


@router.post("/feedback/reason", status_code=200)
async def update_feedback_reason(
    update: ReasonUpdateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Add or update the reason category for an existing feedback event.

    This matches the UI pattern where:
      1. User clicks 👍 or 👎 immediately
      2. A dialog appears asking for more detail (optional)
      3. If user selects a reason, this endpoint is called

    Can be called any time after the initial /feedback submission.
    """
    feedback_repo = FeedbackRepository(db)

    updated = await feedback_repo.update_reason(
        signal_id=update.signal_id,
        thumbs_up_reason=(
            update.thumbs_up_reason.value
            if update.thumbs_up_reason else None
        ),
        thumbs_down_reason=(
            update.thumbs_down_reason.value
            if update.thumbs_down_reason else None
        ),
        feedback_text=update.feedback_text,
    )

    if not updated:
        return JSONResponse(
            status_code=404,
            content={
                "error": "signal_not_found",
                "detail": f"No feedback found with signal_id: {update.signal_id}",
            },
        )

    return {
        "status": "updated",
        "signal_id": update.signal_id,
        "thumbs_up_reason": (
            update.thumbs_up_reason.value
            if update.thumbs_up_reason else None
        ),
        "thumbs_down_reason": (
            update.thumbs_down_reason.value
            if update.thumbs_down_reason else None
        ),
    }


@router.get("/feedback/{response_id}")
async def get_feedback_for_response(
    response_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Retrieve all feedback events and confidence score for a response.
    """
    feedback_repo = FeedbackRepository(db)
    confidence_tracker = ConfidenceTracker(db)
    correction_repo = CorrectionRepository(db)

    events = await feedback_repo.get_feedback_for_response(response_id)
    confidence = await confidence_tracker.get_score(response_id)
    corrections = await correction_repo.get_corrections_for_response(response_id)

    return {
        "response_id": response_id,
        "feedback_count": len(events),
        "confidence_score": confidence.confidence_score if confidence else None,
        "positive_count": confidence.positive_count if confidence else 0,
        "negative_count": confidence.negative_count if confidence else 0,
        "corrections_generated": len(corrections),
        "events": [
            {
                "signal_id": e.get("signal_id"),
                "feedback_type": e.get("feedback_type"),
                "thumbs_up_reason": e.get("thumbs_up_reason"),
                "thumbs_down_reason": e.get("thumbs_down_reason"),
                "signal_strength": e.get("signal_strength"),
                "has_text": bool(e.get("feedback_text")),
                "has_correction": bool(e.get("user_correction")),
                "created_at": e.get("created_at"),
            }
            for e in events
        ],
        "corrections": [
            {
                "correction_id": c.get("correction_id"),
                "classification": c.get("issue_classification"),
                "source": c.get("correction_source"),
                "successful": c.get("received_positive_feedback", False),
            }
            for c in corrections
        ],
    }