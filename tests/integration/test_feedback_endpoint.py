import pytest
from unittest.mock import AsyncMock, patch
from tests.helpers import make_mock_llm_response


async def generate_response(ac, db, payload, mock_llm):
    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        response = await ac.post("/v1/generate", json=payload)
    assert response.status_code == 200
    return response.json()["response_id"]


@pytest.mark.asyncio
async def test_thumbs_up_accepted(client, sample_context_payload):
    ac, db = client
    response_id = await generate_response(
        ac, db, sample_context_payload, make_mock_llm_response()
    )
    fb_payload = {
        "response_id": response_id,
        "session_id": "integration-test-session",
        "feedback_type": "thumbs_up",
        "thumbs_up_reason": "accurate",
        "feedback_text": "Great answer!",
        "tenant_id": "test-tenant",
    }
    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(return_value=make_mock_llm_response()),
    ):
        response = await ac.post("/v1/feedback", json=fb_payload)

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "accepted"
    assert data["signal_type"] == "positive"
    assert data["signal_strength"] == 1.0
    assert data["positive_count"] == 1
    assert data["negative_count"] == 0
    assert data["confidence_score"] == 1.0


@pytest.mark.asyncio
async def test_thumbs_down_triggers_correction(client, sample_context_payload):
    ac, db = client
    response_id = await generate_response(
        ac, db, sample_context_payload, make_mock_llm_response()
    )
    fb_payload = {
        "response_id": response_id,
        "session_id": "integration-test-session",
        "feedback_type": "thumbs_down",
        "thumbs_down_reason": "factually_incorrect",
        "feedback_text": "The answer missed the Calvin cycle.",
        "user_correction": "Photosynthesis includes light reactions and the Calvin cycle.",
        "tenant_id": "test-tenant",
    }
    mock_classify = make_mock_llm_response()
    mock_classify.choices[0].message.content = (
        '{"classification": "factual_error", "reason": "Missing Calvin cycle"}'
    )
    mock_regen = make_mock_llm_response(
        answer="Photosynthesis has two stages: light reactions and the Calvin cycle."
    )
    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(side_effect=[mock_classify, mock_regen]),
    ):
        response = await ac.post("/v1/feedback", json=fb_payload)

    assert response.status_code == 201
    data = response.json()
    assert data["signal_type"] == "correction"
    assert data["negative_count"] == 1
    assert data["confidence_score"] == 0.0
    assert data["corrected_answer"] is not None
    assert data["correction_id"] is not None


@pytest.mark.asyncio
async def test_confidence_score_updates_correctly(client, sample_context_payload):
    ac, db = client
    response_id = await generate_response(
        ac, db, sample_context_payload, make_mock_llm_response()
    )
    base_fb = {
        "response_id": response_id,
        "session_id": "integration-test-session",
        "tenant_id": "test-tenant",
    }
    mock_c = make_mock_llm_response()
    mock_c.choices[0].message.content = '{"classification": "unknown", "reason": "test"}'
    mock_r = make_mock_llm_response()

    for _ in range(3):
        await ac.post("/v1/feedback", json={**base_fb, "feedback_type": "thumbs_up"})

    with patch(
        "app.core.correction_engine.acompletion",
        new=AsyncMock(side_effect=[mock_c, mock_r]),
    ):
        await ac.post("/v1/feedback", json={**base_fb, "feedback_type": "thumbs_down"})

    stats = await ac.get(f"/v1/feedback/{response_id}")
    data = stats.json()
    assert data["positive_count"] == 3
    assert data["negative_count"] == 1
    assert data["confidence_score"] == 0.75


@pytest.mark.asyncio
async def test_feedback_for_nonexistent_response(client):
    ac, db = client
    fb_payload = {
        "response_id": "resp_does_not_exist",
        "session_id": "sess_001",
        "feedback_type": "thumbs_up",
        "tenant_id": "default",
    }
    response = await ac.post("/v1/feedback", json=fb_payload)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reason_update_endpoint(client, sample_context_payload):
    ac, db = client
    response_id = await generate_response(
        ac, db, sample_context_payload, make_mock_llm_response()
    )
    fb = await ac.post("/v1/feedback", json={
        "response_id": response_id,
        "session_id": "integration-test-session",
        "feedback_type": "thumbs_up",
        "tenant_id": "test-tenant",
    })
    signal_id = fb.json()["signal_id"]

    reason_response = await ac.post("/v1/feedback/reason", json={
        "signal_id": signal_id,
        "thumbs_up_reason": "easy_to_understand",
        "feedback_text": "Very clear explanation.",
    })
    assert reason_response.status_code == 200
    data = reason_response.json()
    assert data["status"] == "updated"
    assert data["thumbs_up_reason"] == "easy_to_understand"