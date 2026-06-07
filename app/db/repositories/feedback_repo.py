from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
from app.models.feedback import FeedbackRequest, FeedbackSignal
from app.db.collections import Collections
from app.utils.logger import get_logger
from app.utils.exceptions import DatabaseError

logger = get_logger(__name__)


class FeedbackRepository:
    """Handles all read/write operations for raw feedback events."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[Collections.FEEDBACK]

    async def save_feedback(
        self,
        feedback_request: FeedbackRequest,
        signal: FeedbackSignal,
    ) -> str:
        """
        Saves the raw feedback event and the processed signal together.
        This gives you a complete audit trail: what the user clicked,
        what text they wrote, and what signal was generated.
        """
        document = {
            "_id": signal.signal_id,
            "signal_id": signal.signal_id,
            "response_id": feedback_request.response_id,
            "session_id": feedback_request.session_id,
            "tenant_id": feedback_request.tenant_id,
            "feedback_type": feedback_request.feedback_type.value,
            "feedback_text": feedback_request.feedback_text,
            "user_correction": feedback_request.user_correction,
            "signal_strength": signal.signal_strength,
            "source_ids": signal.source_ids,
            "created_at": datetime.now(timezone.utc),
        }
        try:
            await self.collection.insert_one(document)
            logger.info(
                "feedback_saved",
                signal_id=signal.signal_id,
                response_id=feedback_request.response_id,
                feedback_type=feedback_request.feedback_type.value,
            )
            return signal.signal_id
        except Exception as e:
            raise DatabaseError(
                f"Failed to save feedback: {e}",
                collection=Collections.FEEDBACK,
            )

    async def get_feedback_for_response(self, response_id: str) -> list[dict]:
        """Returns all feedback events for a given response_id."""
        try:
            cursor = self.collection.find({"response_id": response_id})
            return await cursor.to_list(length=100)
        except Exception as e:
            raise DatabaseError(
                f"Failed to fetch feedback: {e}",
                collection=Collections.FEEDBACK,
            )
        
    async def update_reason(
        self,
        signal_id: str,
        thumbs_up_reason: str | None,
        thumbs_down_reason: str | None,
        feedback_text: str | None,
    ) -> bool:
        """Updates the reason on an existing feedback event."""
        update_fields = {}
        if thumbs_up_reason:
            update_fields["thumbs_up_reason"] = thumbs_up_reason
        if thumbs_down_reason:
            update_fields["thumbs_down_reason"] = thumbs_down_reason
        if feedback_text:
            update_fields["feedback_text"] = feedback_text

        if not update_fields:
            return False

        try:
            result = await self.collection.update_one(
                {"signal_id": signal_id},
                {"$set": update_fields},
            )
            return result.modified_count > 0
        except Exception as e:
            raise DatabaseError(
                f"Failed to update reason: {e}",
                collection=Collections.FEEDBACK,
            ) from e