import re
from app.models.context import AssembledContext, SourceDocument
from app.models.response import LLMResponse, FormattedResponse
from app.models.validation import ValidationResult
from app.utils.logger import get_logger
from app.utils.exceptions import FormatterError

logger = get_logger(__name__)


# Confidence label thresholds — shown to the user in the response
CONFIDENCE_LABELS = [
    (0.85, "High confidence"),
    (0.65, "Moderate confidence"),
    (0.45, "Low confidence"),
    (0.0,  "Very low confidence — verify independently"),
]


def _get_confidence_label(score: float) -> str:
    """Maps a 0-1 confidence score to a human-readable label."""
    for threshold, label in CONFIDENCE_LABELS:
        if score >= threshold:
            return label
    return "Very low confidence — verify independently"


def _build_source_lookup(context: AssembledContext) -> dict[str, SourceDocument]:
    """Builds a fast source_id → SourceDocument lookup map."""
    return {doc.source_id: doc for doc in context.source_documents}


def _format_inline_citations(answer: str, source_lookup: dict[str, SourceDocument]) -> str:
    """
    Converts raw [source_id] tags in the LLM answer into numbered
    markdown citations like [^1].

    The LLM writes: "Plants use sunlight [src_001] to produce energy [src_002]."
    We produce:     "Plants use sunlight [^1] to produce energy [^2]."

    We also build a stable numbering so the same source always gets
    the same number within one response.
    """
    # Find all unique source IDs cited in the answer, in order of first appearance
    cited_ids_ordered = []
    seen = set()
    for match in re.finditer(r'\[([^\]]+)\]', answer):
        sid = match.group(1)
        if sid in source_lookup and sid not in seen:
            cited_ids_ordered.append(sid)
            seen.add(sid)

    # Assign sequential numbers
    id_to_number = {sid: i + 1 for i, sid in enumerate(cited_ids_ordered)}

    def replace_citation(match: re.Match) -> str:
        sid = match.group(1)
        if sid in id_to_number:
            return f"[^{id_to_number[sid]}]"
        # Not a source citation — leave it unchanged (could be markdown link)
        return match.group(0)

    formatted = re.sub(r'\[([^\]]+)\]', replace_citation, answer)
    return formatted, id_to_number


def _build_sources_panel(
    used_source_ids: list[str],
    source_lookup: dict[str, SourceDocument],
    id_to_number: dict[str, int],
) -> list[dict]:
    """
    Builds the sources panel list returned to the client.
    Each entry contains the number, title, URL, and relevance score
    so the frontend can render a clickable sources panel.
    """
    sources = []
    for sid in used_source_ids:
        if sid not in source_lookup:
            continue
        doc = source_lookup[sid]
        sources.append({
            "number": id_to_number.get(sid, 0),
            "source_id": sid,
            "title": doc.metadata.get("title", "Untitled Source"),
            "url": doc.metadata.get("url", ""),
            "snippet": doc.content[:200].strip() + "..." if len(doc.content) > 200 else doc.content,
            "relevance_score": round(doc.score, 3),
        })

    # Sort by citation number so the panel order matches the inline numbers
    sources.sort(key=lambda s: s["number"])
    return sources


def _build_footnotes(
    id_to_number: dict[str, int],
    source_lookup: dict[str, SourceDocument],
) -> str:
    """
    Builds a markdown footnote block appended at the bottom of the answer.

    Example output:
        [^1]: Biology Basics — https://example.com/bio
        [^2]: Plant Science
    """
    if not id_to_number:
        return ""

    lines = []
    for sid, number in sorted(id_to_number.items(), key=lambda x: x[1]):
        if sid not in source_lookup:
            continue
        doc = source_lookup[sid]
        title = doc.metadata.get("title", "Source")
        url = doc.metadata.get("url", "")
        if url:
            lines.append(f"[^{number}]: {title} — {url}")
        else:
            lines.append(f"[^{number}]: {title}")

    return "\n".join(lines)


def _add_confidence_header(
    answer: str,
    confidence_score: float,
    passed: bool,
) -> str:
    """
    Prepends confidence notices and validation warnings.
    """

    if not passed:
        warning = (
            "> **[WARNING] Quality notice:** This answer did not pass all validation checks. "
            "Please verify the information independently.\n\n"
        )
        return warning + answer

    label = _get_confidence_label(confidence_score)

    if confidence_score < 0.65:
        notice = (
            f"> **[NOTE] {label}.** "
            "The retrieved sources may not fully cover this question.\n\n"
        )
        return notice + answer

    return answer


def format_response(
    llm_response: LLMResponse,
    validation_result: ValidationResult,
    context: AssembledContext,
) -> FormattedResponse:
    """
    Main entry point for the formatter.

    Takes the raw LLM output and validation scores,
    produces a fully formatted response ready for the client.

    Never raises — if something goes wrong it degrades gracefully
    and returns the raw answer unformatted rather than crashing.
    """
    try:
        source_lookup = _build_source_lookup(context)

        # Replace [source_id] tags with numbered [^N] citations
        formatted_answer, id_to_number = _format_inline_citations(
            llm_response.raw_answer, source_lookup
        )

        # Build the sources panel for the frontend
        sources_panel = _build_sources_panel(
            llm_response.source_ids, source_lookup, id_to_number
        )

        # Append footnote references at the bottom
        footnotes = _build_footnotes(id_to_number, source_lookup)
        if footnotes:
            formatted_answer = formatted_answer + "\n\n---\n" + footnotes

        # Add confidence header or warning banner
        formatted_answer = _add_confidence_header(
            formatted_answer,
            llm_response.confidence_score,
            validation_result.passed,
        )

        logger.info(
            "response_formatted",
            response_id=llm_response.response_id,
            sources_cited=len(id_to_number),
            validation_passed=validation_result.passed,
            confidence=llm_response.confidence_score,
        )

        return FormattedResponse(
            response_id=llm_response.response_id,
            session_id=llm_response.session_id,
            answer=formatted_answer,
            confidence_score=llm_response.confidence_score,
            validation_passed=validation_result.passed,
            source_ids=llm_response.source_ids,
            sources=sources_panel,
            model_used=llm_response.model_used,
            latency_ms=llm_response.latency_ms,
            created_at=llm_response.created_at,
        )

    except Exception as e:
        # Degrade gracefully — never crash the whole pipeline
        logger.error(
            "formatter_error",
            response_id=llm_response.response_id,
            error=str(e),
        )
        raise FormatterError(f"Formatting failed: {e}") from e