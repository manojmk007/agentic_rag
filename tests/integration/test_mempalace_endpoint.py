import pytest
from unittest.mock import AsyncMock, patch
from tests.helpers import make_mock_llm_response


async def generate_and_feedback(ac, payload, feedback_type="thumbs_up"):
    mock_llm = make_mock_llm_response()
    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        gen = await ac.post("/v1/generate", json=payload)
    response_id = gen.json()["response_id"]

    fb = {
        "response_id": response_id,
        "session_id": payload["session_id"],
        "feedback_type": feedback_type,
        "tenant_id": payload["tenant_id"],
    }
    mock_c = make_mock_llm_response()
    mock_c.choices[0].message.content = '{"classification": "unknown", "reason": "test"}'
    mock_r = make_mock_llm_response()

    if feedback_type == "thumbs_down":
        with patch(
            "app.core.correction_engine.acompletion",
            new=AsyncMock(side_effect=[mock_c, mock_r]),
        ):
            await ac.post("/v1/feedback", json=fb)
    else:
        await ac.post("/v1/feedback", json=fb)

    return response_id


@pytest.mark.asyncio
async def test_stats_endpoint_returns_counts(client, sample_context_payload):
    ac, db = client
    await generate_and_feedback(ac, sample_context_payload, "thumbs_up")
    await generate_and_feedback(ac, sample_context_payload, "thumbs_up")

    response = await ac.get("/v1/mempalace/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_signals"] >= 2
    assert data["positive_signals"] >= 2
    assert data["unprocessed_signals"] >= 2


@pytest.mark.asyncio
async def test_batch_endpoint_returns_signals(client, sample_context_payload):
    ac, db = client
    await generate_and_feedback(ac, sample_context_payload, "thumbs_up")

    response = await ac.get("/v1/mempalace/batch?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "batch_id" in data
    assert data["total_count"] >= 1
    assert len(data["signals"]) >= 1
    assert data["signals"][0]["signal_type"] in [
        "positive", "negative", "correction", "positive_with_correction"
    ]


@pytest.mark.asyncio
async def test_mark_processed_endpoint(client, sample_context_payload):
    ac, db = client
    await generate_and_feedback(ac, sample_context_payload, "thumbs_up")

    batch_response = await ac.get("/v1/mempalace/batch?limit=10")
    signals = batch_response.json()["signals"]
    signal_ids = [s["signal_id"] for s in signals]

    mark_response = await ac.patch(
        "/v1/mempalace/processed",
        json=signal_ids,
    )
    assert mark_response.status_code == 200
    assert mark_response.json()["marked_processed"] == len(signal_ids)

    stats = await ac.get("/v1/mempalace/stats")
    assert stats.json()["unprocessed_signals"] == 0


@pytest.mark.asyncio
async def test_get_single_signal(client, sample_context_payload):
    ac, db = client
    await generate_and_feedback(ac, sample_context_payload, "thumbs_up")

    batch = await ac.get("/v1/mempalace/batch?limit=1")
    signal_id = batch.json()["signals"][0]["signal_id"]

    response = await ac.get(f"/v1/mempalace/signal/{signal_id}")
    assert response.status_code == 200
    assert response.json()["signal_id"] == signal_id


@pytest.mark.asyncio
async def test_get_nonexistent_signal(client):
    ac, db = client
    response = await ac.get("/v1/mempalace/signal/sig_does_not_exist")
    assert response.status_code == 404