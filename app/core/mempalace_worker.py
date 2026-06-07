import ulid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import Collections
from app.models.mempalace import MemPalaceEntry, MemPalaceSignalBatch
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_unprocessed_batch(
    db: AsyncIOMotorDatabase,
    batch_size: int = 50,
) -> MemPalaceSignalBatch:
    """
    Fetches the next batch of unprocessed MemPalace signals.

    Signals are returned oldest-first so the MemPalace team
    processes them in the order they were generated.
    The MemPalace worker calls this, processes each signal,
    then calls mark_signals_processed() with the signal IDs.
    """
    collection = db[Collections.MEMPALACE_SIGNALS]

    cursor = collection.find(
        {"processed": False}
    ).sort("created_at", 1).limit(batch_size)

    docs = await cursor.to_list(length=batch_size)

    if not docs:
        return MemPalaceSignalBatch(
            batch_id=f"batch_{ulid.new()}",
            signals=[],
            total_count=0,
            oldest_signal_age_seconds=None,
        )

    signals = []
    for doc in docs:
        doc.pop("_id", None)
        signals.append(MemPalaceEntry(**doc))

    # Calculate age of oldest signal in this batch
    oldest_created = docs[0].get("created_at")
    age_seconds = None
    if oldest_created:
        now = datetime.now(timezone.utc)
        if oldest_created.tzinfo is None:
            oldest_created = oldest_created.replace(tzinfo=timezone.utc)
        age_seconds = (now - oldest_created).total_seconds()

    batch = MemPalaceSignalBatch(
        batch_id=f"batch_{ulid.new()}",
        signals=signals,
        total_count=len(signals),
        oldest_signal_age_seconds=age_seconds,
    )

    logger.info(
        "mempalace_batch_prepared",
        batch_id=batch.batch_id,
        signal_count=len(signals),
        oldest_age_seconds=age_seconds,
    )

    return batch


async def mark_signals_processed(
    db: AsyncIOMotorDatabase,
    signal_ids: list[str],
) -> int:
    """
    Marks a list of signal IDs as processed.
    Called by the MemPalace worker after successfully consuming signals.
    Returns the count of documents actually updated.
    """
    if not signal_ids:
        return 0

    collection = db[Collections.MEMPALACE_SIGNALS]

    result = await collection.update_many(
        {"signal_id": {"$in": signal_ids}},
        {
            "$set": {
                "processed": True,
                "processed_at": datetime.now(timezone.utc),
            }
        },
    )

    logger.info(
        "signals_marked_processed",
        count=result.modified_count,
        signal_ids=signal_ids,
    )

    return result.modified_count


async def get_queue_stats(db: AsyncIOMotorDatabase) -> dict:
    """
    Returns queue health statistics.
    Used by the /v1/mempalace/stats endpoint.
    """
    collection = db[Collections.MEMPALACE_SIGNALS]
    now = datetime.now(timezone.utc)
    last_24h = datetime(
        now.year, now.month, now.day,
        now.hour, now.minute, now.second,
        tzinfo=timezone.utc,
    )

    # Run aggregation queries in parallel using individual awaits
    total = await collection.count_documents({})
    unprocessed = await collection.count_documents({"processed": False})
    processed = await collection.count_documents({"processed": True})
    positive = await collection.count_documents(
        {"signal_type": {"$in": ["positive", "positive_with_correction"]}}
    )
    negative = await collection.count_documents({"signal_type": "negative"})
    corrections = await collection.count_documents({"signal_type": "correction"})

    # Last 24h count
    from datetime import timedelta
    yesterday = now - timedelta(hours=24)
    last_24h_count = await collection.count_documents(
        {"created_at": {"$gte": yesterday}}
    )

    # Oldest unprocessed signal age
    oldest_cursor = collection.find(
        {"processed": False}
    ).sort("created_at", 1).limit(1)
    oldest_docs = await oldest_cursor.to_list(length=1)

    oldest_age = None
    if oldest_docs:
        oldest_created = oldest_docs[0].get("created_at")
        if oldest_created:
            if oldest_created.tzinfo is None:
                oldest_created = oldest_created.replace(tzinfo=timezone.utc)
            oldest_age = (now - oldest_created).total_seconds()

    return {
        "total_signals": total,
        "unprocessed_signals": unprocessed,
        "processed_signals": processed,
        "positive_signals": positive,
        "negative_signals": negative,
        "correction_signals": corrections,
        "oldest_unprocessed_age_seconds": oldest_age,
        "signals_last_24h": last_24h_count,
    }