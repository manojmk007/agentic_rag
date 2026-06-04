"""
orchestrator/models/output_models.py
=======================================
Data models for Step 10 — Final Orchestrator Output.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field

from orchestrator.models.context_models import ContextPackage


class OrchestratorOutput(BaseModel):
    """
    Final structured JSON output of the Cognitive Orchestrator.
    This is the ONLY thing returned to the downstream Answer Generation System.
    """

    # ── Query Understanding ──────────────────────────────────
    intent: str = Field(..., description="Detected user intent")
    topic: str = Field(default="general", description="Current conversation topic")
    entities: list[str] = Field(default_factory=list, description="Extracted entities")

    # ── Routing ──────────────────────────────────────────────
    selected_routes: list[str] = Field(
        default_factory=list,
        description="Active routes: conversation, memory, document, fresh",
    )
    retrieval_required: bool = Field(
        default=True,
        description="Whether retrieval was performed",
    )
    budget_level: str = Field(
        default="medium",
        description="Retrieval budget used: skip, low, medium, high",
    )

    # ── Evidence ─────────────────────────────────────────────
    evidence_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Composite evidence confidence score",
    )
    context_package: ContextPackage = Field(
        default_factory=ContextPackage,
        description="Assembled context for the LLM",
    )

    # ── Risk ─────────────────────────────────────────────────
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Risk flags from safety checks",
    )

    # ── Orchestrator Meta ────────────────────────────────────
    orchestrator_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Overall orchestrator confidence in context quality",
    )
    resolved_query: str = Field(
        default="",
        description="Query after coreference resolution and optimization",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if orchestrator recommends asking user for clarification",
    )
    clarification_reason: str = Field(
        default="",
        description="Why clarification is needed",
    )
    self_correction_count: int = Field(
        default=0,
        description="Number of self-correction retries performed",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Step timings, debug info, correction history",
    )
