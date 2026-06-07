import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.correction_engine import classify_issue, regenerate_answer
from app.models.feedback import (
    FeedbackRequest,
    FeedbackType,
    ThumbsDownReason,
    IssueClassification,
)


def make_feedback(**overrides) -> FeedbackRequest:
    defaults = dict(
        response_id="resp_001",
        session_id="sess_001",
        feedback_type=FeedbackType.THUMBS_DOWN,
        thumbs_down_reason=ThumbsDownReason.FACTUALLY_INCORRECT,
        feedback_text="The answer was wrong.",
        tenant_id="default",
    )
    defaults.update(overrides)
    return FeedbackRequest(**defaults)


@pytest.mark.asyncio
async def test_classify_issue_returns_classification():
    feedback = make_feedback()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"classification": "factual_error", "reason": "Answer had wrong facts"}'
    )

    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await classify_issue(feedback, "Wrong answer text here.")

    assert result == IssueClassification.FACTUAL_ERROR


@pytest.mark.asyncio
async def test_classify_issue_returns_unknown_on_parse_error():
    feedback = make_feedback()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "not valid json at all"

    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await classify_issue(feedback, "Some answer.")

    assert result == IssueClassification.UNKNOWN


@pytest.mark.asyncio
async def test_regenerate_answer_returns_improved():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is the improved answer."

    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await regenerate_answer(
            original_answer="Wrong answer.",
            user_query="What is photosynthesis?",
            issue_classification=IssueClassification.FACTUAL_ERROR,
            correction_context=None,
            user_correction=None,
        )

    assert result == "This is the improved answer."


@pytest.mark.asyncio
async def test_regenerate_answer_falls_back_on_error():
    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(side_effect=Exception("LLM down")),
    ):
        result = await regenerate_answer(
            original_answer="Original answer.",
            user_query="What is X?",
            issue_classification=IssueClassification.UNKNOWN,
            correction_context=None,
            user_correction=None,
        )

    # Must fall back gracefully to original
    assert result == "Original answer."