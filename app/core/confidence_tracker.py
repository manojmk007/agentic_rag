from datetime import datetime, timezone
from pymongo import ReturnDocument
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.feedback import ConfidenceScore, FeedbackType
from app.db.collections import Collections
from app.utils.logger import get_logger
from app.utils.exceptions import DatabaseError

logger = get_logger(__name__)


class ConfidenceTracker:
    """
    Tracks positive and negative feedback counts per response.

    Every time feedback arrives:
      - Increments the appropriate counter atomically in MongoDB
      - Recalculates confidence_score = positive / (positive + negative)
      - Updates the llm_responses document with the new score

    This score is later used by the retrieval pipeline to rank
    memories — higher confidence memories surface first.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.responses = db[Collections.RESPONSES]
        self.scores = db["confidence_scores"]

    async def record_feedback(
        self,
        response_id: str,
        feedback_type: FeedbackType,
    ) -> ConfidenceScore:
        """
        Atomically increments the counter and returns the updated score.
        Uses MongoDB $inc so concurrent feedback events never conflict.
        """
        # Determine which counter to increment
        increment_field = (
            "positive_count"
            if feedback_type == FeedbackType.THUMBS_UP
            else "negative_count"
        )

        # Upsert — creates the document on first feedback, updates on subsequent
        result = await self.scores.find_one_and_update(
            {"response_id": response_id},
            {
                "$inc": {increment_field: 1},
                "$setOnInsert": {"response_id": response_id},
                "$set": {"last_updated": datetime.now(timezone.utc)},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        positive = result.get("positive_count", 0)
        negative = result.get("negative_count", 0)

        score = ConfidenceScore.calculate(positive, negative, response_id)

        # Write the recalculated score back
        await self.scores.update_one(
            {"response_id": response_id},
            {"$set": {
                "confidence_score": score.confidence_score,
                "positive_count": positive,
                "negative_count": negative,
            }},
        )

        # Also update the main response document so retrieval can use it
        await self.responses.update_one(
            {"_id": response_id},
            {"$set": {"feedback_confidence_score": score.confidence_score}},
        )

        logger.info(
            "confidence_score_updated",
            response_id=response_id,
            feedback_type=feedback_type.value,
            positive_count=positive,
            negative_count=negative,
            confidence_score=score.confidence_score,
        )

        return score

    async def get_score(self, response_id: str) -> ConfidenceScore | None:
        """Returns the current confidence score for a response."""
        doc = await self.scores.find_one({"response_id": response_id})
        if not doc:
            return None
        return ConfidenceScore(
            response_id=doc["response_id"],
            positive_count=doc.get("positive_count", 0),
            negative_count=doc.get("negative_count", 0),
            confidence_score=doc.get("confidence_score", 0.0),
            last_updated=doc.get("last_updated", datetime.now(timezone.utc)),
        )