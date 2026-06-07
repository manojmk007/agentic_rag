from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Any


class MemPalaceEntry(BaseModel):
    """
    A feedback signal formatted for storage in MemPalace.

    The MemPalace team's workers poll the mempalace_signals collection
    filtering on processed=False ordered by created_at ascending.

    After consuming a signal they call PATCH /v1/mempalace/{signal_id}/processed
    to mark it done.
    """
    signal_id: str
    response_id: str
    session_id: str
    tenant_id: str
    signal_type: str = Field(
        ...,
        description=(
            "positive | negative | correction | "
            "positive_with_correction"
        ),
    )
    signal_strength: float = Field(ge=0.0, le=1.0)
    source_ids: list[str] = Field(default_factory=list)
    user_correction: str | None = None
    feedback_text: str | None = None
    processed: bool = Field(
        default=False,
        description="Set to True by MemPalace worker after consuming",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemPalaceSignalBatch(BaseModel):
    """A batch of unprocessed signals returned to the MemPalace worker."""
    batch_id: str
    signals: list[MemPalaceEntry]
    total_count: int
    oldest_signal_age_seconds: float | None = None


class MemPalaceStats(BaseModel):
    """Current health stats for the MemPalace signal queue."""
    total_signals: int
    unprocessed_signals: int
    processed_signals: int
    positive_signals: int
    negative_signals: int
    correction_signals: int
    oldest_unprocessed_age_seconds: float | None
    signals_last_24h: int