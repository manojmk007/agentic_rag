"""
orchestrator/services/retrieval_interface.py
==============================================
Abstract retrieval interface — retrieval-agnostic design.
The orchestrator defines WHAT to retrieve; backends define HOW.

Included implementations:
  - MockRetriever: for testing with predefined chunks
  - HTTPRetriever: calls an external retrieval API
"""

from abc import ABC, abstractmethod
from typing import Optional, Any

import httpx

from orchestrator.models.context_models import RetrievedChunk
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class RetrievalInterface(ABC):
    """Abstract base class for retrieval backends."""

    @abstractmethod
    async def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 50,
        filters: Optional[dict] = None,
    ) -> list[RetrievedChunk]:
        """
        Retrieve chunks matching the query.

        Args:
            query: The search query string.
            query_vector: Pre-computed query embedding (optional).
            top_k: Maximum number of results to return.
            filters: Optional metadata filters.

        Returns:
            List of RetrievedChunk objects, sorted by relevance.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the retrieval backend is available."""
        ...


class MockRetriever(RetrievalInterface):
    """
    Mock retriever for testing.
    Returns predefined chunks or empty results.
    """

    def __init__(self, chunks: Optional[list[dict]] = None):
        self._chunks = chunks or []

    async def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 50,
        filters: Optional[dict] = None,
    ) -> list[RetrievedChunk]:
        results = []
        for c in self._chunks[:top_k]:
            results.append(RetrievedChunk(
                id=c.get("id", ""),
                text=c.get("text", ""),
                score=c.get("score", 0.5),
                source=c.get("source", "mock"),
                metadata=c.get("metadata", {}),
            ))
        return results

    async def health_check(self) -> bool:
        return True


class HTTPRetriever(RetrievalInterface):
    """
    HTTP-based retriever that calls an external API.
    Compatible with any REST API that returns JSON chunks.

    Expected API response format:
    {
        "chunks": [
            {"id": "...", "text": "...", "score": 0.9, "source": "...", "metadata": {...}}
        ]
    }
    """

    def __init__(
        self,
        base_url: str,
        search_endpoint: str = "/query",
        health_endpoint: str = "/health",
        timeout: float = 30.0,
        headers: Optional[dict] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._search_endpoint = search_endpoint
        self._health_endpoint = health_endpoint
        self._timeout = timeout
        self._headers = headers or {"Content-Type": "application/json"}

    @track_latency("http_retrieval")
    async def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 50,
        filters: Optional[dict] = None,
    ) -> list[RetrievedChunk]:
        url = f"{self._base_url}{self._search_endpoint}"
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "stream": False,
        }
        if filters:
            payload["filters"] = filters

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, json=payload, headers=self._headers
                )
                response.raise_for_status()
                data = response.json()

            chunks_data = data.get("chunks", [])
            results = []
            for c in chunks_data:
                results.append(RetrievedChunk(
                    id=c.get("id", ""),
                    text=c.get("text", ""),
                    score=c.get("score", 0.0),
                    source=c.get("source", "http"),
                    metadata=c.get("metadata", {}),
                ))
            logger.info("http_retrieval_complete", count=len(results), url=url)
            return results

        except Exception as e:
            logger.error("http_retrieval_failed", url=url, error=str(e))
            return []

    async def health_check(self) -> bool:
        url = f"{self._base_url}{self._health_endpoint}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            return False


# ── Factory ──────────────────────────────────────────────────

def create_retriever(
    backend: str = "mock", **kwargs
) -> RetrievalInterface:
    """
    Factory to create a retrieval backend.

    Args:
        backend: "mock" | "http"
        **kwargs: Backend-specific arguments.

    Returns:
        A RetrievalInterface implementation.
    """
    if backend == "http":
        return HTTPRetriever(
            base_url=kwargs.get("base_url", "http://localhost:8000"),
            search_endpoint=kwargs.get("search_endpoint", "/query"),
            health_endpoint=kwargs.get("health_endpoint", "/health"),
        )
    return MockRetriever(chunks=kwargs.get("chunks", []))
