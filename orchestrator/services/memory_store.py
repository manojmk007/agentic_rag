"""
orchestrator/services/memory_store.py
=======================================
Lightweight memory service — MongoDB-backed.
Stores agent memories with embedded vectors for semantic retrieval.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from orchestrator.config.settings import settings
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.embedder_service import embedder_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class MemoryStore:
    """MongoDB-backed memory store with vector search capability."""

    @track_latency("memory_store")
    async def store_memory(
        self,
        query: str,
        answer: str,
        category: str = "general",
        confidence: float = 0.8,
        metadata: Optional[dict] = None,
    ) -> str:
        """Store a memory with its embedding vector."""
        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        vector = await embedder_service.embed_query(query)

        doc = {
            "memory_id": memory_id,
            "query": query,
            "answer": answer,
            "category": category.lower(),
            "confidence": confidence,
            "embedding": vector,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }

        collection = mongodb_service.memories
        await collection.insert_one(doc)
        logger.info("memory_stored", id=memory_id, category=category)
        return memory_id

    @track_latency("memory_search")
    async def search_memories(
        self,
        query: str,
        limit: int = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Search memories by semantic similarity.
        Uses embedding cosine similarity for ranking.
        """
        limit = limit or settings.memory_max_results
        query_vector = await embedder_service.embed_query(query)
        collection = mongodb_service.memories

        # Try MongoDB vector search if index exists
        try:
            return await self._vector_search(
                collection, query_vector, limit, category
            )
        except Exception as e:
            logger.debug("vector_search_unavailable", error=str(e))
            # Fallback: brute-force similarity over all memories
            return await self._brute_force_search(
                collection, query_vector, limit, category
            )

    async def _vector_search(
        self, collection, query_vector: list[float], limit: int, category: Optional[str]
    ) -> list[dict]:
        """Attempt MongoDB Atlas $vectorSearch."""
        filter_stage: dict = {}
        if category:
            filter_stage = {"category": category.lower()}

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "memory_vector_index",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": limit * 10,
                    "limit": limit,
                    **({"filter": filter_stage} if filter_stage else {}),
                }
            },
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {"$match": {"score": {"$gte": settings.memory_min_threshold}}},
            {"$project": {"embedding": 0}},
        ]

        results = await collection.aggregate(pipeline).to_list(limit)
        return [
            {
                "id": r["memory_id"],
                "query": r.get("query", ""),
                "answer": r.get("answer", ""),
                "category": r.get("category", ""),
                "score": round(float(r.get("score", 0)), 4),
                "confidence": r.get("confidence", 0.0),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]

    async def _brute_force_search(
        self, collection, query_vector: list[float], limit: int, category: Optional[str]
    ) -> list[dict]:
        """Fallback: fetch all memories and compute similarity in Python."""
        query_filter = {}
        if category:
            query_filter["category"] = category.lower()

        cursor = collection.find(query_filter).sort("created_at", -1).limit(200)
        docs = await cursor.to_list(200)

        scored = []
        for doc in docs:
            embedding = doc.get("embedding")
            if not embedding:
                continue
            sim = embedder_service.cosine_similarity(query_vector, embedding)
            if sim >= settings.memory_min_threshold:
                scored.append({
                    "id": doc["memory_id"],
                    "query": doc.get("query", ""),
                    "answer": doc.get("answer", ""),
                    "category": doc.get("category", ""),
                    "score": round(sim, 4),
                    "confidence": doc.get("confidence", 0.0),
                    "metadata": doc.get("metadata", {}),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    @track_latency("memory_semantic_cache")
    async def check_semantic_cache(
        self, query: str
    ) -> Optional[dict[str, Any]]:
        """Check if a semantically similar query was recently answered."""
        results = await self.search_memories(query, limit=1, category=None)
        if results and results[0]["score"] >= settings.memory_cache_threshold:
            logger.info("semantic_cache_hit", score=results[0]["score"])
            return results[0]
        return None

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        collection = mongodb_service.memories
        result = await collection.delete_one({"memory_id": memory_id})
        return result.deleted_count > 0

    async def get_stats(self) -> dict:
        """Return memory store statistics."""
        collection = mongodb_service.memories
        total = await collection.count_documents({})
        categories = await collection.distinct("category")
        return {
            "total_memories": total,
            "categories": categories,
        }


# Module-level singleton
memory_store = MemoryStore()
