from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class ThumbsUpReason(str, Enum):
    ACCURATE = "accurate"
    EASY_TO_UNDERSTAND = "easy_to_understand"
    COMPLETE_ANSWER = "complete_answer"
    HELPFUL_EXAMPLES = "helpful_examples"
    OTHER = "other"


class ThumbsDownReason(str, Enum):
    FACTUALLY_INCORRECT = "factually_incorrect"
    OUTDATED_INFORMATION = "outdated_information"
    MISSING_DETAILS = "missing_details"
    NOT_RELEVANT = "not_relevant"
    POOR_EXPLANATION = "poor_explanation"
    OTHER = "other"
    NOT_PROVIDED = "not_provided"


class IssueClassification(str, Enum):
    """
    Auto-classified by the LLM when thumbs down is received.
    Drives what kind of correction to attempt.
    """
    FACTUAL_ERROR = "factual_error"
    COMPLETENESS_GAP = "completeness_gap"
    RELEVANCE_MISMATCH = "relevance_mismatch"
    OUTDATED_CONTENT = "outdated_content"
    CLARITY_ISSUE = "clarity_issue"
    UNKNOWN = "unknown"


class FeedbackRequest(BaseModel):
    """What the client sends when the user gives feedback."""
    response_id: str = Field(..., description="The response being rated")
    session_id: str = Field(..., description="Session this feedback belongs to")
    feedback_type: FeedbackType
    # Optional reason category — sent in the same request or via /reason endpoint
    thumbs_up_reason: ThumbsUpReason | None = Field(
        default=None,
        description="Why the user liked this answer"
    )
    thumbs_down_reason: ThumbsDownReason | None = Field(
        default=None,
        description="Why the user disliked this answer"
    )
    feedback_text: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional free-text feedback"
    )
    user_correction: str | None = Field(
        default=None,
        max_length=5000,
        description="If user provides a better answer"
    )
    tenant_id: str = Field(default="default")


class ReasonUpdateRequest(BaseModel):
    """
    Sent after the initial feedback to add a reason category.
    This matches the UI pattern where reason is an optional second step.
    """
    signal_id: str
    thumbs_up_reason: ThumbsUpReason | None = None
    thumbs_down_reason: ThumbsDownReason | None = None
    feedback_text: str | None = Field(default=None, max_length=2000)


class FeedbackSignal(BaseModel):
    """Processed feedback ready to be written to MemPalace."""
    signal_id: str
    response_id: str
    session_id: str
    feedback_type: FeedbackType
    signal_strength: float = Field(ge=0.0, le=1.0)
    thumbs_up_reason: ThumbsUpReason | None = None
    thumbs_down_reason: ThumbsDownReason | None = None
    issue_classification: IssueClassification | None = None
    source_ids: list[str] = Field(default_factory=list)
    user_correction: str | None = None
    feedback_text: str | None = None
    tenant_id: str = Field(default="default")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfidenceScore(BaseModel):
    """
    Tracks positive/negative feedback counts per response.
    confidence_score = positive_count / (positive_count + negative_count)
    """
    response_id: str
    positive_count: int = Field(default=0, ge=0)
    negative_count: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def calculate(cls, positive: int, negative: int, response_id: str) -> "ConfidenceScore":
        total = positive + negative
        score = positive / total if total > 0 else 0.0
        return cls(
            response_id=response_id,
            positive_count=positive,
            negative_count=negative,
            confidence_score=round(score, 4),
        )


class CorrectedAnswer(BaseModel):
    """
    Stores both the original and corrected answer after a thumbs down
    triggers the memory-aware correction engine.
    """
    correction_id: str
    response_id: str
    signal_id: str
    session_id: str
    original_answer: str
    corrected_answer: str
    issue_classification: IssueClassification
    correction_source: str = Field(
        description="memory | regenerated | user_provided"
    )
    user_correction_used: str | None = None
    received_positive_feedback: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )