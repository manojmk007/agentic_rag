import pytest
from app.core.feedback_processor import (
    process_feedback,
    _compute_signal_strength,
    _determine_signal_type,
)
from app.models.feedback import FeedbackRequest, FeedbackType


def make_feedback(**overrides) -> FeedbackRequest:
    defaults = dict(
        response_id="resp_001",
        session_id="sess_001",
        feedback_type=FeedbackType.THUMBS_UP,
        feedback_text=None,
        user_correction=None,
        tenant_id="default",
    )
    defaults.update(overrides)
    return FeedbackRequest(**defaults)


SOURCE_IDS = ["src_001", "src_002"]


# ── Signal strength ───────────────────────────────────────────────────────────

def test_thumbs_up_signal_strength():
    feedback = make_feedback(feedback_type=FeedbackType.THUMBS_UP)
    strength = _compute_signal_strength(feedback)
    assert strength == 1.0


def test_thumbs_down_signal_strength():
    feedback = make_feedback(feedback_type=FeedbackType.THUMBS_DOWN)
    strength = _compute_signal_strength(feedback)
    assert strength == 1.0   # absolute value stored; type carries the sign


def test_thumbs_up_with_correction_boosted():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_UP,
        user_correction="Better answer here.",
    )
    strength = _compute_signal_strength(feedback)
    assert strength == 1.0   # boosted but clamped at 1.0


def test_thumbs_down_with_correction_not_boosted():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        user_correction="The answer should be X.",
    )
    strength = _compute_signal_strength(feedback)
    assert strength == 1.0


# ── Signal type ───────────────────────────────────────────────────────────────

def test_signal_type_positive():
    feedback = make_feedback(feedback_type=FeedbackType.THUMBS_UP)
    assert _determine_signal_type(feedback) == "positive"


def test_signal_type_negative():
    feedback = make_feedback(feedback_type=FeedbackType.THUMBS_DOWN)
    assert _determine_signal_type(feedback) == "negative"


def test_signal_type_positive_with_correction():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_UP,
        user_correction="Better answer.",
    )
    assert _determine_signal_type(feedback) == "positive_with_correction"


def test_signal_type_correction():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        user_correction="The correct answer is X.",
    )
    assert _determine_signal_type(feedback) == "correction"


# ── Full process_feedback ─────────────────────────────────────────────────────

def test_process_feedback_returns_signal_and_entry():
    feedback = make_feedback(feedback_type=FeedbackType.THUMBS_UP)
    signal, entry = process_feedback(feedback, SOURCE_IDS)

    assert signal.response_id == "resp_001"
    assert signal.signal_strength == 1.0
    assert signal.source_ids == SOURCE_IDS
    assert entry.signal_type == "positive"
    assert entry.processed is False
    assert entry.signal_id == signal.signal_id


def test_process_feedback_negative_sets_correct_type():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        feedback_text="This answer was wrong.",
    )
    signal, entry = process_feedback(feedback, SOURCE_IDS)

    assert entry.signal_type == "negative"
    assert entry.metadata["has_text_feedback"] is True
    assert entry.metadata["has_correction"] is False


def test_process_feedback_correction_sets_metadata():
    feedback = make_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        user_correction="The correct answer is photosynthesis requires CO2.",
    )
    signal, entry = process_feedback(feedback, SOURCE_IDS)

    assert entry.signal_type == "correction"
    assert entry.user_correction == "The correct answer is photosynthesis requires CO2."
    assert entry.metadata["has_correction"] is True


def test_process_feedback_generates_unique_signal_ids():
    feedback = make_feedback()
    signal1, _ = process_feedback(feedback, SOURCE_IDS)
    signal2, _ = process_feedback(feedback, SOURCE_IDS)
    assert signal1.signal_id != signal2.signal_id