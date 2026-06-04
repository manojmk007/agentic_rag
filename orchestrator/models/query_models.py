"""
orchestrator/models/query_models.py
=====================================
Data models for Step 1 — Query Understanding.
"""

from enum import Enum
from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Classification of user query into routing categories."""
    FOLLOW_UP = "FollowUp"
    CONVERSATION = "Conversation"
    MEMORY = "Memory"
    DOCUMENT = "Document"
    HYBRID = "Hybrid"
    FRESH_DATA = "FreshData"
    TASK_EXECUTION = "TaskExecution"
    UNKNOWN = "Unknown"


class QueryAnalysis(BaseModel):
    """Output of Step 1 — comprehensive query understanding."""

    intent: str = Field(
        ..., description="What the user wants: lookup, compare, explain, recall, execute, converse"
    )
    domain: str = Field(
        default="general",
        description="Auto-classified domain: technical, scientific, business, general",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Classifier confidence in intent detection",
    )
    ambiguity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="How ambiguous the query is (0=clear, 1=very ambiguous)",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Named entities, technical terms, references extracted",
    )
    query_type: QueryType = Field(
        default=QueryType.UNKNOWN,
        description="Classified query routing category",
    )
    objective: str = Field(
        default="",
        description="Brief statement of what the user wants to achieve",
    )
    complexity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Query complexity: 0=trivial, 1=highly complex",
    )
    requires_context: bool = Field(
        default=True,
        description="Whether the query requires external context to answer",
    )
    temporal_signals: list[str] = Field(
        default_factory=list,
        description="Temporal references found (e.g., 'latest', '2026', 'yesterday')",
    )
