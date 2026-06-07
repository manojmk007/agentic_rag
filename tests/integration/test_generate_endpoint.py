import pytest
from unittest.mock import AsyncMock, patch
from tests.helpers import make_mock_llm_response


@pytest.mark.asyncio
async def test_generate_returns_formatted_response(client, sample_context_payload):
    ac, db = client
    mock_llm = make_mock_llm_response()

    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        response = await ac.post("/v1/generate", json=sample_context_payload)

    assert response.status_code == 200
    data = response.json()
    assert "response_id" in data
    assert data["response_id"].startswith("resp_")
    assert "answer" in data
    assert data["confidence_score"] == 0.88
    assert data["session_id"] == "integration-test-session"
    assert isinstance(data["sources"], list)
    assert data["model_used"] is not None


@pytest.mark.asyncio
async def test_generate_persists_to_database(client, sample_context_payload):
    ac, db = client
    mock_llm = make_mock_llm_response()

    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        response = await ac.post("/v1/generate", json=sample_context_payload)

    assert response.status_code == 200
    response_id = response.json()["response_id"]

    doc = await db["llm_responses"].find_one({"_id": response_id})
    assert doc is not None
    assert doc["session_id"] == "integration-test-session"
    assert doc["confidence_score"] == 0.88


@pytest.mark.asyncio
async def test_generate_missing_query_returns_422(client):
    ac, db = client
    bad_payload = {
        "session_id": "sess_001",
        "source_documents": [],
    }
    response = await ac.post("/v1/generate", json=bad_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_retrieve_by_id(client, sample_context_payload):
    ac, db = client
    mock_llm = make_mock_llm_response()

    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        gen_response = await ac.post("/v1/generate", json=sample_context_payload)

    response_id = gen_response.json()["response_id"]
    get_response = await ac.get(f"/v1/generate/{response_id}")
    assert get_response.status_code == 200
    assert get_response.json()["response_id"] == response_id


@pytest.mark.asyncio
async def test_generate_with_empty_sources(client):
    ac, db = client
    mock_llm = make_mock_llm_response(
        answer="I don't have enough information to answer this."
    )
    payload = {
        "session_id": "sess_no_sources",
        "user_query": "What is photosynthesis?",
        "source_documents": [],
        "tenant_id": "default",
    }
    with patch("app.core.llm_service.acompletion", new=AsyncMock(return_value=mock_llm)):
        response = await ac.post("/v1/generate", json=payload)

    assert response.status_code == 200
    assert "answer" in response.json()


@pytest.mark.asyncio
async def test_generate_llm_failure_returns_502(client, sample_context_payload):
    ac, db = client
    import litellm

    with patch(
        "app.core.llm_service.acompletion",
        new=AsyncMock(
            side_effect=litellm.exceptions.AuthenticationError(
                "bad key", llm_provider="gemini", model="gemini"
            )
        ),
    ):
        response = await ac.post("/v1/generate", json=sample_context_payload)

    assert response.status_code == 502