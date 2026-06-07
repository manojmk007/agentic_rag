from fastapi import APIRouter, Depends, Body
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dependencies import get_db
from app.core.mempalace_worker import (
    get_unprocessed_batch,
    mark_signals_processed,
    get_queue_stats,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/mempalace/batch")
async def get_signal_batch(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Returns a batch of unprocessed MemPalace signals.

    Called by the MemPalace team's worker to consume signals.
    After processing, call PATCH /v1/mempalace/processed with
    the list of signal_ids to mark them done.

    limit: max signals per batch (default 50, max 200)
    """
    limit = min(limit, 200)
    batch = await get_unprocessed_batch(db=db, batch_size=limit)

    return {
        "batch_id": batch.batch_id,
        "total_count": batch.total_count,
        "oldest_signal_age_seconds": batch.oldest_signal_age_seconds,
        "signals": [s.model_dump() for s in batch.signals],
    }


@router.patch("/mempalace/processed")
async def mark_processed(
    signal_ids: list[str] = Body(
        ...,
        description="List of signal_ids to mark as processed",
        example=["sig_01J...", "sig_01J..."],
    ),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Marks signals as processed after the MemPalace worker consumes them.
    Call this after your worker successfully stores each signal in MemPalace.
    """
    count = await mark_signals_processed(db=db, signal_ids=signal_ids)

    return {
        "status": "ok",
        "marked_processed": count,
        "submitted_ids": len(signal_ids),
    }


@router.get("/mempalace/stats")
async def queue_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Returns current queue health statistics.
    Use this to monitor signal backlog and throughput.
    """
    stats = await get_queue_stats(db=db)
    return stats


@router.get("/mempalace/signal/{signal_id}")
async def get_signal(
    signal_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Fetch a single signal by its ID. Useful for debugging."""
    from app.db.collections import Collections
    doc = await db[Collections.MEMPALACE_SIGNALS].find_one(
        {"signal_id": signal_id}
    )
    if not doc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={"error": "signal_not_found", "signal_id": signal_id},
        )
    doc.pop("_id", None)
    return doc