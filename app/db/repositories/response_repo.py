from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.response import LLMResponse, FormattedResponse
from app.db.collections import Collections
from app.utils.logger import get_logger
from app.utils.exceptions import DatabaseError, ResponseNotFoundError

logger = get_logger(__name__)


class ResponseRepository:
    """Handles all read/write operations for LLM responses."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[Collections.RESPONSES]

    async def save_response(
        self,
        llm_response: LLMResponse,
        formatted_response: FormattedResponse,
    ) -> str:
        """
        Persists both the raw LLM response and the formatted response
        in a single document. We store both so we can debug issues
        without losing the raw LLM output.
        """
        document = {
            "_id": llm_response.response_id,
            "response_id": llm_response.response_id,
            "session_id": llm_response.session_id,
            "raw_answer": llm_response.raw_answer,
            "formatted_answer": formatted_response.answer,
            "source_ids": llm_response.source_ids,
            "sources": formatted_response.sources,
            "confidence_score": llm_response.confidence_score,
            "validation_passed": formatted_response.validation_passed,
            "model_used": llm_response.model_used,
            "prompt_tokens": llm_response.prompt_tokens,
            "completion_tokens": llm_response.completion_tokens,
            "latency_ms": llm_response.latency_ms,
            "created_at": llm_response.created_at,
            "metadata": llm_response.metadata,
        }
        try:
            await self.collection.insert_one(document)
            logger.info("response_saved", response_id=llm_response.response_id)
            return llm_response.response_id
        except Exception as e:
            raise DatabaseError(
                f"Failed to save response: {e}",
                collection=Collections.RESPONSES,
            )

    async def get_response(self, response_id: str) -> dict:
        """Fetches a stored response by ID. Raises if not found."""
        try:
            doc = await self.collection.find_one({"_id": response_id})
        except Exception as e:
            raise DatabaseError(
                f"Failed to fetch response: {e}",
                collection=Collections.RESPONSES,
            )
        if doc is None:
            raise ResponseNotFoundError(response_id)
        return doc

    async def response_exists(self, response_id: str) -> bool:
        """Lightweight check — does this response_id exist?"""
        try:
            count = await self.collection.count_documents(
                {"_id": response_id}, limit=1
            )
            return count > 0
        except Exception:
            return False