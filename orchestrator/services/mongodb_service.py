"""
orchestrator/services/mongodb_service.py
==========================================
Async MongoDB connection manager using Motor.
Manages collections for conversations, memories, analytics, and cache.
"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger

logger = get_logger(__name__)


class MongoDBService:
    """Async MongoDB connection manager for the Orchestrator."""

    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Connect to MongoDB and ensure indexes exist."""
        if self._initialized:
            return

        self._client = AsyncIOMotorClient(
            settings.mongodb_uri,
            maxPoolSize=settings.mongodb_max_pool_size,
        )
        self._db = self._client[settings.mongodb_database]

        # ── Ensure indexes ────────────────────────────────────
        # Conversations: TTL index for auto-expiry
        await self._db.conversations.create_index(
            "updated_at",
            expireAfterSeconds=settings.conversation_ttl_seconds,
        )
        await self._db.conversations.create_index("session_id", unique=True)

        # Memories: indexes for efficient lookup
        await self._db.memories.create_index("category")
        await self._db.memories.create_index("created_at")

        # Cache: TTL index
        await self._db.cache.create_index(
            "expires_at", expireAfterSeconds=0
        )
        await self._db.cache.create_index(
            [("key", 1), ("cache_type", 1)], unique=True
        )

        # Analytics
        await self._db.analytics.create_index("metric_type")

        # Document Chunks
        await self._db.document_chunks.create_index([("doc_id", 1), ("metadata.chunk_index", 1)], unique=True)
        await self._db.document_chunks.create_index([("text", "text")])
        await self._db.document_chunks.create_index("metadata.tenant_id")

        self._initialized = True
        logger.info(
            "mongodb_initialized",
            database=settings.mongodb_database,
            uri=settings.mongodb_uri[:30] + "...",
        )

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoDB not initialized. Call initialize() first.")
        return self._db

    @property
    def conversations(self):
        return self.db.conversations

    @property
    def memories(self):
        return self.db.memories

    @property
    def cache(self):
        return self.db.cache

    @property
    def analytics(self):
        return self.db.analytics

    @property
    def document_chunks(self):
        return self.db.document_chunks

    async def health_check(self) -> bool:
        """Ping MongoDB to check connectivity."""
        try:
            if self._client:
                await self._client.admin.command("ping")
                return True
            return False
        except Exception:
            return False

    async def close(self) -> None:
        """Gracefully close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._initialized = False
            logger.info("mongodb_closed")


# Module-level singleton
mongodb_service = MongoDBService()
