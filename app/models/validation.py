from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Scores and outcome from the response validation module."""
    response_id: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    citation_coverage_score: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    flagged_for_review: bool = Field(default=False)