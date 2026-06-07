from app.models.feedback import (
    FeedbackRequest,
    FeedbackSignal,
    FeedbackType,
    ThumbsDownReason,
)
from app.models.mempalace import MemPalaceEntry
from app.utils.id_generator import generate_signal_id
from app.utils.logger import get_logger
from app.utils.exceptions import FeedbackProcessingError

logger = get_logger(__name__)

SIGNAL_STRENGTH_MAP = {
    FeedbackType.THUMBS_UP: 1.0,
    FeedbackType.THUMBS_DOWN: 1.0,
}
CORRECTION_BOOST = 0.2


def _compute_signal_strength(feedback: FeedbackRequest) -> float:
    base = SIGNAL_STRENGTH_MAP[feedback.feedback_type]
    if (
        feedback.user_correction
        and feedback.feedback_type == FeedbackType.THUMBS_UP
    ):
        base = min(base + CORRECTION_BOOST, 1.0)
    return round(base, 3)


def _determine_signal_type(feedback: FeedbackRequest) -> str:
    if feedback.feedback_type == FeedbackType.THUMBS_UP:
        return (
            "positive_with_correction"
            if feedback.user_correction
            else "positive"
        )
    else:
        return "correction" if feedback.user_correction else "negative"


def _normalize_thumbs_down_reason(feedback: FeedbackRequest) -> str | None:
    """
    If no reason was provided with thumbs down, default to not_provided.
    This ensures we always have a reason field for analytics.
    """
    if feedback.feedback_type == FeedbackType.THUMBS_DOWN:
        if feedback.thumbs_down_reason is None:
            return ThumbsDownReason.NOT_PROVIDED.value
        return feedback.thumbs_down_reason.value
    return None


def process_feedback(
    feedback_request: FeedbackRequest,
    source_ids: list[str],
) -> tuple[FeedbackSignal, MemPalaceEntry]:
    """
    Converts a raw FeedbackRequest into a FeedbackSignal
    and a MemPalaceEntry. Does not run the correction flow —
    that is handled separately in the API layer because it
    needs async DB access.
    """
    try:
        signal_id = generate_signal_id()
        signal_strength = _compute_signal_strength(feedback_request)
        signal_type = _determine_signal_type(feedback_request)
        normalized_down_reason = _normalize_thumbs_down_reason(feedback_request)

        signal = FeedbackSignal(
            signal_id=signal_id,
            response_id=feedback_request.response_id,
            session_id=feedback_request.session_id,
            feedback_type=feedback_request.feedback_type,
            signal_strength=signal_strength,
            thumbs_up_reason=feedback_request.thumbs_up_reason,
            thumbs_down_reason=feedback_request.thumbs_down_reason,
            source_ids=source_ids,
            user_correction=feedback_request.user_correction,
            feedback_text=feedback_request.feedback_text,
            tenant_id=feedback_request.tenant_id,
        )

        mempalace_entry = MemPalaceEntry(
            signal_id=signal_id,
            response_id=feedback_request.response_id,
            session_id=feedback_request.session_id,
            tenant_id=feedback_request.tenant_id,
            signal_type=signal_type,
            signal_strength=signal_strength,
            source_ids=source_ids,
            user_correction=feedback_request.user_correction,
            feedback_text=feedback_request.feedback_text,
            processed=False,
            metadata={
                "feedback_type": feedback_request.feedback_type.value,
                "thumbs_up_reason": (
                    feedback_request.thumbs_up_reason.value
                    if feedback_request.thumbs_up_reason else None
                ),
                "thumbs_down_reason": normalized_down_reason,
                "has_text_feedback": bool(feedback_request.feedback_text),
                "has_correction": bool(feedback_request.user_correction),
            },
        )

        logger.info(
            "feedback_processed",
            signal_id=signal_id,
            response_id=feedback_request.response_id,
            signal_type=signal_type,
            signal_strength=signal_strength,
        )

        return signal, mempalace_entry

    except Exception as e:
        raise FeedbackProcessingError(
            f"Failed to process feedback: {e}"
        ) from e