"""
orchestrator/models/conversation_models.py
============================================
Data models for Step 2 — Conversation Intelligence.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """A single turn in conversation history."""
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="The message content")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entities: list[str] = Field(default_factory=list)
    topic: str = Field(default="general")


class ConversationState(BaseModel):
    """Output of Step 2 — conversation intelligence analysis."""

    followup: bool = Field(
        default=False,
        description="Whether this query is a follow-up to the previous turn",
    )
    context_switch: bool = Field(
        default=False,
        description="Whether the user switched topics from the previous turn",
    )
    resolved_entities: list[str] = Field(
        default_factory=list,
        description="Entities resolved from coreferences (it, that, this, etc.)",
    )
    resolved_query: str = Field(
        default="",
        description="Query with coreferences replaced by actual entities",
    )
    conversation_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence that conversation context alone can answer the query",
    )
    current_topic: str = Field(default="general")
    previous_topics: list[str] = Field(default_factory=list)
    conversation_summary: str = Field(
        default="",
        description="LLM-compressed summary of older conversation turns",
    )
    recent_turns: list[ConversationTurn] = Field(
        default_factory=list,
        description="Last N full turns for context",
    )
    turn_count: int = Field(default=0)
