from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.mempalace import MemPalaceEntry
from app.db.collections import Collections
from app.utils.logger import get_logger
from app.utils.exceptions import MemPalaceError

logger = get_logger(__name__)


class MemPalaceRepository:
    """
    Writes processed feedback signals to the MemPalace collection.
    The MemPalace team's workers poll this collection and consume
    the signals to update memory scores and semantic facts.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[Collections.MEMPALACE_SIGNALS]

    async def write_signal(self, entry: MemPalaceEntry) -> str:
        """
        Writes a single feedback signal to the MemPalace collection.
        Sets processed=False so the MemPalace worker knows to pick it up.
        """
        document = {
            "_id": entry.signal_id,
            **entry.model_dump(),
        }
        try:
            await self.collection.insert_one(document)
            logger.info(
                "mempalace_signal_written",
                signal_id=entry.signal_id,
                signal_type=entry.signal_type,
                response_id=entry.response_id,
                session_id=entry.session_id,
            )
            return entry.signal_id
        except Exception as e:
            raise MemPalaceError(
                f"Failed to write MemPalace signal: {e}"
            ) from e

    async def mark_processed(self, signal_id: str) -> None:
        """Called by the MemPalace team's worker after consuming a signal."""
        try:
            await self.collection.update_one(
                {"_id": signal_id},
                {"$set": {"processed": True}},
            )
        except Exception as e:
            raise MemPalaceError(
                f"Failed to mark signal as processed: {e}"
            ) from e

    async def get_unprocessed_signals(self, limit: int = 50) -> list[dict]:
        """Returns signals not yet consumed by MemPalace workers."""
        try:
            cursor = self.collection.find(
                {"processed": False}
            ).sort("created_at", 1).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            raise MemPalaceError(
                f"Failed to fetch unprocessed signals: {e}"
            ) from e