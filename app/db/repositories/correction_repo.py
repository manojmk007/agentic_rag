from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.feedback import CorrectedAnswer
from app.utils.logger import get_logger
from app.utils.exceptions import DatabaseError

logger = get_logger(__name__)
COLLECTION = "corrected_answers"


class CorrectionRepository:
    """
    Stores corrected answers produced by the correction engine.
    Tracks whether corrections later receive positive feedback —
    this tells you how effective the correction engine is.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[COLLECTION]

    async def save_correction(self, correction: CorrectedAnswer) -> str:
        document = {
            "_id": correction.correction_id,
            **correction.model_dump(),
        }
        try:
            await self.collection.insert_one(document)
            logger.info(
                "correction_saved",
                correction_id=correction.correction_id,
                response_id=correction.response_id,
                source=correction.correction_source,
                classification=correction.issue_classification.value,
            )
            return correction.correction_id
        except Exception as e:
            raise DatabaseError(f"Failed to save correction: {e}") from e

    async def mark_correction_successful(self, response_id: str) -> None:
        """
        Called when a corrected answer later receives thumbs up.
        Marks received_positive_feedback=True for analytics.
        """
        try:
            await self.collection.update_many(
                {"response_id": response_id},
                {"$set": {"received_positive_feedback": True}},
            )
            logger.info(
                "correction_marked_successful",
                response_id=response_id,
            )
        except Exception as e:
            raise DatabaseError(
                f"Failed to mark correction successful: {e}"
            ) from e

    async def get_corrections_for_response(
        self, response_id: str
    ) -> list[dict]:
        """Returns all corrections for a given response."""
        try:
            cursor = self.collection.find({"response_id": response_id})
            return await cursor.to_list(length=10)
        except Exception as e:
            raise DatabaseError(
                f"Failed to fetch corrections: {e}"
            ) from e