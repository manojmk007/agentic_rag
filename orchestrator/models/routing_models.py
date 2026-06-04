"""
orchestrator/models/routing_models.py
=======================================
Data models for Step 3 (Route Scoring) and Step 4 (Retrieval Budget).
"""

from typing import Literal
from pydantic import BaseModel, Field


class RouteScores(BaseModel):
    """Output of Step 3 — independent confidence score per route."""

    conversation_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence that conversation context can answer",
    )
    memory_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence that memory/recall can answer",
    )
    document_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence that document retrieval is needed",
    )
    fresh_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence that fresh/live data is needed",
    )


class RetrievalBudget(BaseModel):
    """Output of Step 4 — retrieval budget allocation decision."""

    retrieve: bool = Field(
        default=True,
        description="Whether retrieval should be performed at all",
    )
    budget_level: Literal["skip", "low", "medium", "high"] = Field(
        default="medium",
        description="Budget level controlling retrieval depth",
    )
    selected_routes: list[str] = Field(
        default_factory=list,
        description="Which routes are active: conversation, memory, document, fresh",
    )
    top_k: int = Field(
        default=50,
        description="Number of results to retrieve per source",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of budget decision",
    )
