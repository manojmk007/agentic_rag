"""
orchestrator/api/models.py
============================
Pydantic request/response models for the Orchestrator API.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class OrchestrateRequest(BaseModel):
    """Request body for the /orchestrate endpoint."""
    query: str = Field(..., description="The user's query to orchestrate")
    session_id: Optional[str] = Field(
        None, description="Session ID for conversation tracking (auto-generated if None)"
    )
    tenant_id: Optional[str] = Field(
        None, description="Tenant ID for multi-tenant isolation"
    )
    filters: Optional[dict[str, Any]] = Field(
        None, description="Optional metadata filters for retrieval"
    )


class HealthResponse(BaseModel):
    """Response for the /health endpoint."""
    status: str
    services: dict[str, bool]


class ConversationHistoryResponse(BaseModel):
    """Response for the /conversations/{session_id} endpoint."""
    session_id: str
    turns: list[dict[str, Any]]
    turn_count: int
