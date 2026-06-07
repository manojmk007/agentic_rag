import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.llm_service import generate_response, _parse_llm_output, _build_messages
from app.models.context import AssembledContext, SourceDocument
from app.utils.exceptions import LLMServiceError


def make_context(**overrides) -> AssembledContext:
    """Helper — builds a minimal valid AssembledContext for tests."""
    defaults = dict(
        session_id="test-session-001",
        user_query="What is photosynthesis?",
        source_documents=[
            SourceDocument(
                source_id="src_001",
                content="Photosynthesis is the process by which plants convert sunlight to energy.",
                score=0.95,
                metadata={"title": "Biology Basics"},
            ),
            SourceDocument(
                source_id="src_002",
                content="Chlorophyll absorbs light and drives the photosynthesis reaction.",
                score=0.88,
                metadata={"title": "Plant Science"},
            ),
        ],
        tenant_id="test-tenant",
    )
    defaults.update(overrides)
    return AssembledContext(**defaults)


# ── _parse_llm_output tests ───────────────────────────────────────────────────

def test_parse_llm_output_happy_path():
    raw = (
        'Photosynthesis converts sunlight [src_001].\n\n'
        '{"confidence": 0.92, "used_source_ids": ["src_001", "src_002"]}'
    )
    docs = make_context().source_documents
    answer, confidence, ids = _parse_llm_output(raw, docs)

    assert "Photosynthesis" in answer
    assert confidence == 0.92
    assert "src_001" in ids
    assert "src_002" in ids
    # JSON block removed from answer
    assert "confidence" not in answer


def test_parse_llm_output_clamps_confidence():
    raw = 'Some answer.\n{"confidence": 1.5, "used_source_ids": []}'
    docs = make_context().source_documents
    _, confidence, _ = _parse_llm_output(raw, docs)
    assert confidence == 1.0


def test_parse_llm_output_rejects_invalid_source_ids():
    raw = 'Answer.\n{"confidence": 0.8, "used_source_ids": ["fake_id_999"]}'
    docs = make_context().source_documents
    _, _, ids = _parse_llm_output(raw, docs)
    # fake_id_999 is not in source_documents — must be filtered out
    assert ids == []


def test_parse_llm_output_no_json_block():
    raw = "Just a plain answer with no JSON."
    docs = make_context().source_documents
    answer, confidence, ids = _parse_llm_output(raw, docs)
    assert answer == raw
    assert confidence == 0.5   # safe default
    assert ids == []


# ── _build_messages tests ─────────────────────────────────────────────────────

def test_build_messages_structure():
    ctx = make_context()
    messages = _build_messages(ctx)

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    # Source content must be in the final user message
    assert "src_001" in messages[-1]["content"]
    assert "photosynthesis" in messages[-1]["content"].lower()


def test_build_messages_includes_history():
    ctx = make_context(conversation_history=[
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ])
    messages = _build_messages(ctx)
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


def test_build_messages_includes_memory():
    ctx = make_context(memory_context="User prefers concise answers.")
    messages = _build_messages(ctx)
    assert "User prefers concise answers" in messages[-1]["content"]


# ── generate_response integration (mocked LLM) ───────────────────────────────

@pytest.mark.asyncio
async def test_generate_response_success():
    ctx = make_context()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        'Photosynthesis converts light [src_001].\n'
        '{"confidence": 0.9, "used_source_ids": ["src_001"]}'
    )
    mock_response.usage = MagicMock(prompt_tokens=150, completion_tokens=80)

    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await generate_response(ctx)

    assert result.session_id == "test-session-001"
    assert result.confidence_score == 0.9
    assert "src_001" in result.source_ids
    assert result.prompt_tokens == 150
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_generate_response_raises_on_auth_error():
    import litellm
    ctx = make_context()

    with patch(
        "app.core.llm_service.acompletion",
        new=AsyncMock(side_effect=litellm.exceptions.AuthenticationError(
            "invalid key", llm_provider="gemini", model="gemini-1.5-flash"
        ))
    ):
        with pytest.raises(LLMServiceError) as exc_info:
            await generate_response(ctx)
    assert "API key" in str(exc_info.value)