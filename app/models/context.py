from pydantic import BaseModel, Field
from typing import Any


class SourceDocument(BaseModel):
    """A single retrieved document chunk passed in the assembled context."""
    source_id: str = Field(..., description="Unique ID of this document chunk")
    content: str = Field(..., description="The actual text content of the chunk")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Retrieval relevance score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Title, url, timestamp etc.")


class AssembledContext(BaseModel):
    """
    The input this service receives from the Context Assembly stage.
    This is the contract with the upstream team.
    """
    session_id: str = Field(..., description="Conversation session identifier")
    user_query: str = Field(..., min_length=1, description="The original user question")
    system_prompt: str = Field(
        default="You are a helpful, accurate assistant. Answer based only on the provided context.",
        description="System prompt from orchestration layer"
    )
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Prior turns: [{'role': 'user'|'assistant', 'content': '...'}]"
    )
    source_documents: list[SourceDocument] = Field(
        default_factory=list,
        description="Retrieved document chunks from hybrid search"
    )
    memory_context: str = Field(
        default="",
        description="Relevant memories from MemPalace for this session"
    )
    fresh_context: str = Field(
        default="",
        description="Fresh knowledge from web search or internal KB updates"
    )
    max_tokens: int | None = Field(default=None, description="Override default max tokens")
    tenant_id: str = Field(default="default", description="Multi-tenant identifier")