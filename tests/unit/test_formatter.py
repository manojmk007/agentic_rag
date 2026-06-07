import pytest
from datetime import datetime, timezone
from app.core.formatter import (
    format_response,
    _get_confidence_label,
    _format_inline_citations,
    _build_sources_panel,
    _build_footnotes,
    _add_confidence_header,
)
from app.models.context import AssembledContext, SourceDocument
from app.models.response import LLMResponse
from app.models.validation import ValidationResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_source(source_id: str, title: str, score: float = 0.9, url: str = "") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        content=f"Content for {title}. " * 20,
        score=score,
        metadata={"title": title, "url": url},
    )


def make_llm_response(**overrides) -> LLMResponse:
    defaults = dict(
        response_id="resp_001",
        session_id="sess_001",
        raw_answer="Photosynthesis converts sunlight [src_001] into energy using chlorophyll [src_002].",
        source_ids=["src_001", "src_002"],
        confidence_score=0.88,
        model_used="gemini/gemini-1.5-flash",
        prompt_tokens=200,
        completion_tokens=60,
        latency_ms=410.0,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return LLMResponse(**defaults)


def make_validation(passed: bool = True, **overrides) -> ValidationResult:
    defaults = dict(
        response_id="resp_001",
        confidence_score=0.88,
        citation_coverage_score=1.0,
        relevance_score=0.9,
        overall_score=0.88,
        passed=passed,
        failure_reasons=[] if passed else ["Low confidence"],
        flagged_for_review=False,
    )
    defaults.update(overrides)
    return ValidationResult(**defaults)


def make_context(**overrides) -> AssembledContext:
    defaults = dict(
        session_id="sess_001",
        user_query="What is photosynthesis?",
        source_documents=[
            make_source("src_001", "Biology Basics", 0.95, "https://bio.example.com"),
            make_source("src_002", "Plant Science", 0.88, "https://plant.example.com"),
        ],
    )
    defaults.update(overrides)
    return AssembledContext(**defaults)


# ── Confidence label ──────────────────────────────────────────────────────────

def test_confidence_label_high():
    assert _get_confidence_label(0.90) == "High confidence"


def test_confidence_label_moderate():
    assert _get_confidence_label(0.70) == "Moderate confidence"


def test_confidence_label_low():
    assert _get_confidence_label(0.50) == "Low confidence"


def test_confidence_label_very_low():
    assert _get_confidence_label(0.20) == "Very low confidence — verify independently"


# ── Inline citation formatting ────────────────────────────────────────────────

def test_inline_citations_replaced():
    source_lookup = {
        "src_001": make_source("src_001", "Biology"),
        "src_002": make_source("src_002", "Plants"),
    }
    answer = "Plants use sunlight [src_001] and chlorophyll [src_002]."
    formatted, id_to_number = _format_inline_citations(answer, source_lookup)

    assert "[^1]" in formatted
    assert "[^2]" in formatted
    assert "src_001" not in formatted
    assert id_to_number["src_001"] == 1
    assert id_to_number["src_002"] == 2


def test_inline_citations_unknown_ids_untouched():
    source_lookup = {"src_001": make_source("src_001", "Biology")}
    answer = "Answer [src_001] and also [unknown_id]."
    formatted, _ = _format_inline_citations(answer, source_lookup)

    assert "[^1]" in formatted
    # unknown_id is not in source_lookup — must stay as-is
    assert "[unknown_id]" in formatted


def test_inline_citations_same_source_twice():
    source_lookup = {"src_001": make_source("src_001", "Biology")}
    answer = "First mention [src_001]. Second mention [src_001]."
    formatted, id_to_number = _format_inline_citations(answer, source_lookup)

    # Same source always gets the same number
    assert formatted.count("[^1]") == 2
    assert len(id_to_number) == 1


def test_inline_citations_no_citations():
    source_lookup = {"src_001": make_source("src_001", "Biology")}
    answer = "An answer with no citations at all."
    formatted, id_to_number = _format_inline_citations(answer, source_lookup)

    assert formatted == answer
    assert id_to_number == {}


# ── Sources panel ─────────────────────────────────────────────────────────────

def test_sources_panel_structure():
    source_lookup = {
        "src_001": make_source("src_001", "Biology", url="https://bio.example.com"),
    }
    id_to_number = {"src_001": 1}
    panel = _build_sources_panel(["src_001"], source_lookup, id_to_number)

    assert len(panel) == 1
    assert panel[0]["number"] == 1
    assert panel[0]["title"] == "Biology"
    assert panel[0]["url"] == "https://bio.example.com"
    assert panel[0]["source_id"] == "src_001"
    assert "snippet" in panel[0]


def test_sources_panel_sorted_by_number():
    source_lookup = {
        "src_001": make_source("src_001", "Biology"),
        "src_002": make_source("src_002", "Plants"),
    }
    id_to_number = {"src_001": 2, "src_002": 1}
    panel = _build_sources_panel(["src_001", "src_002"], source_lookup, id_to_number)

    assert panel[0]["number"] == 1
    assert panel[1]["number"] == 2


def test_sources_panel_snippet_truncated():
    long_content = "A" * 500
    source_lookup = {
        "src_001": SourceDocument(
            source_id="src_001", content=long_content, score=0.9,
            metadata={"title": "Long Doc"}
        )
    }
    panel = _build_sources_panel(["src_001"], source_lookup, {"src_001": 1})
    assert len(panel[0]["snippet"]) <= 203   # 200 chars + "..."


# ── Confidence header ─────────────────────────────────────────────────────────

def test_confidence_header_not_added_for_high_confidence():
    answer = "This is the answer."
    result = _add_confidence_header(answer, 0.90, passed=True)
    assert result == answer   # no header added


def test_confidence_header_added_for_low_confidence():
    answer = "This is the answer."
    result = _add_confidence_header(answer, 0.50, passed=True)
    assert "[NOTE]" in result
    assert "Low confidence" in result


def test_warning_banner_added_when_validation_failed():
    answer = "This is the answer."
    result = _add_confidence_header(answer, 0.88, passed=False)
    assert "[WARNING]" in result
    assert "did not pass" in result


# ── Full format_response ──────────────────────────────────────────────────────

def test_format_response_full_pipeline():
    response = make_llm_response()
    validation = make_validation(passed=True)
    context = make_context()

    result = format_response(response, validation, context)

    assert result.response_id == "resp_001"
    assert result.validation_passed is True
    assert "[^1]" in result.answer
    assert "[^2]" in result.answer
    assert len(result.sources) == 2
    assert result.confidence_score == 0.88
    # Footnotes appended
    assert "Biology Basics" in result.answer
    assert "Plant Science" in result.answer


def test_format_response_failed_validation_adds_warning():
    response = make_llm_response(confidence_score=0.30)
    validation = make_validation(passed=False)
    context = make_context()

    result = format_response(response, validation, context)

    assert result.validation_passed is False
    assert "[WARNING]" in result.answer


def test_format_response_no_sources():
    response = make_llm_response(
        raw_answer="An answer with no citations.",
        source_ids=[],
    )
    validation = make_validation(passed=True)
    context = make_context(source_documents=[])

    result = format_response(response, validation, context)

    assert result.answer is not None
    assert result.sources == []