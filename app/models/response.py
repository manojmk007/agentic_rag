from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
from typing import Any


class LLMResponse(BaseModel):
    """Raw output from the LLM service before validation and formatting."""
    model_config = ConfigDict(protected_namespaces=())
    response_id: str = Field(..., description="Unique ID for this response")
    session_id: str = Field(..., description="Session this response belongs to")
    raw_answer: str = Field(..., description="Raw text from the LLM")
    source_ids: list[str] = Field(
        default_factory=list,
        description="IDs of source documents the LLM used"
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="LLM self-reported confidence (0-1)"
    )
    model_used: str = Field(..., description="Exact model identifier used")
    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    latency_ms: float = Field(default=0.0, description="LLM call duration in milliseconds")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormattedResponse(BaseModel):
    """Final response returned to the client after validation and formatting."""
    model_config = ConfigDict(protected_namespaces=())
    response_id: str
    session_id: str
    answer: str = Field(..., description="Formatted answer with inline citations")
    confidence_score: float
    validation_passed: bool
    source_ids: list[str]
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Source metadata for the sources panel"
    )
    model_used: str
    latency_ms: float
    created_at: datetime