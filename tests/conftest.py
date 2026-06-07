import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.graph.workflow import init_workflow
from tests.helpers import make_mock_llm_response


@pytest.fixture
def sample_context_payload():
    return {
        "session_id": "integration-test-session",
        "user_query": "What is photosynthesis?",
        "source_documents": [
            {
                "source_id": "src_001",
                "content": (
                    "Photosynthesis is the process by which plants use "
                    "sunlight, water and CO2 to produce glucose and oxygen."
                ),
                "score": 0.95,
                "metadata": {
                    "title": "Biology Basics",
                    "url": "https://example.com/bio",
                },
            },
            {
                "source_id": "src_002",
                "content": (
                    "Chlorophyll in plant cells absorbs light energy "
                    "and drives the photosynthesis reaction."
                ),
                "score": 0.88,
                "metadata": {
                    "title": "Plant Science",
                    "url": "https://example.com/plants",
                },
            },
        ],
        "tenant_id": "test-tenant",
    }


@pytest_asyncio.fixture
async def client():
    """
    Async test client with mocked LLM and in-memory MongoDB.
    Never hits Gemini API or real MongoDB during tests.
    """
    import mongomock_motor

    mock_db = mongomock_motor.AsyncMongoMockClient()["test_rag_service"]

    with patch("app.db.client._database", mock_db), \
         patch("app.db.client._client", MagicMock()), \
         patch("app.db.client.connect_to_mongodb", new=AsyncMock()), \
         patch("app.db.client.close_mongodb_connection", new=AsyncMock()):

        init_workflow(db=mock_db)

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as ac:
            yield ac, mock_db   