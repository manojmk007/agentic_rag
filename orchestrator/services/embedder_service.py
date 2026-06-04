"""
orchestrator/services/embedder_service.py
===========================================
Sentence-transformer embedding service.
Production: BAAI/bge-large-en-v1.5 (1024-dim)
Dev/Test:   all-MiniLM-L6-v2 (384-dim)
"""

import asyncio
import threading
from typing import Optional

import numpy as np

from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class EmbedderService:
    """Thread-safe sentence-transformer embedding service."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._query_cache = {}

    async def _ensure_model(self) -> None:
        """Lazy-load the embedding model on first use."""
        if self._model is not None:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)

    def _load_model(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer
            logger.info("loading_embedding_model", model=settings.embedding_model)
            self._model = SentenceTransformer(
                settings.embedding_model,
                device=settings.embedding_device,
            )
            logger.info(
                "embedding_model_loaded",
                model=settings.embedding_model,
                dim=settings.embedding_dimension,
            )

    @track_latency("embed_query")
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Returns a list of floats."""
        if text in self._query_cache:
            return self._query_cache[text]
            
        await self._ensure_model()
        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(
            None,
            lambda: self._model.encode(text, normalize_embeddings=True).tolist(),
        )
        
        if len(self._query_cache) >= 500:
            self._query_cache.clear()
        self._query_cache[text] = vector
        return vector

    @track_latency("embed_batch")
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a batch."""
        if not texts:
            return []
        await self._ensure_model()
        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts, normalize_embeddings=True, batch_size=32
            ).tolist(),
        )
        return vectors

    @staticmethod
    def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))


# Module-level singleton
embedder_service = EmbedderService()
