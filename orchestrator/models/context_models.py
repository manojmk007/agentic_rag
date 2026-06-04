"""
orchestrator/models/context_models.py
=======================================
Data models for Steps 6, 8, and 9 — Context Quality, Assembly, and Risk.
"""

from typing import Literal, Optional, Any
from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """A single chunk returned by a retrieval backend."""

    id: str = Field(default="")
    text: str = Field(default="")
    score: float = Field(default=0.0)
    source: str = Field(default="unknown")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextQuality(BaseModel):
    """Output of Step 6 — post-retrieval quality evaluation."""

    coverage_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction of query aspects covered by context",
    )
    relevance_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Average semantic relevance of chunks to query",
    )
    freshness_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Recency of source documents",
    )
    conflict_detected: bool = Field(
        default=False,
        description="Whether contradictions were found across chunks",
    )
    duplicate_count: int = Field(
        default=0,
        description="Number of near-duplicate chunks detected",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Query concepts not addressed by any chunk",
    )
    evidence_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Composite evidence confidence score",
    )
    verdict: Literal["sufficient", "marginal", "insufficient"] = Field(
        default="insufficient",
        description="Quality gate verdict",
    )


class ContextPackage(BaseModel):
    """Output of Step 8 — assembled context for downstream LLM."""

    conversation_context: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent conversation turns for continuity",
    )
    user_context: dict[str, Any] = Field(
        default_factory=dict,
        description="User/session metadata and preferences",
    )
    retrieved_evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Deduplicated, ranked document chunks",
    )
    memory_context: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Relevant memories from memory store",
    )
    tool_outputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Results from tool/task executions",
    )
    total_tokens_estimate: int = Field(
        default=0,
        description="Estimated total token count of the package",
    )


class RiskAssessment(BaseModel):
    """Output of Step 9 — risk control gate."""

    safe: bool = Field(
        default=True,
        description="Whether the context package is safe to forward",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Risk flags raised during assessment",
    )
    pii_detected: list[str] = Field(
        default_factory=list,
        description="Types of PII found in context (email, phone, ssn, etc.)",
    )
    injection_detected: bool = Field(
        default=False,
        description="Whether prompt injection was detected",
    )
    blocked: bool = Field(
        default=False,
        description="Whether the request should be blocked entirely",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of risk assessment",
    )
