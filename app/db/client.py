from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level singleton — shared across all requests
_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None


async def connect_to_mongodb() -> None:
    """
    Called once at app startup.
    Creates the Motor client and verifies the connection with a ping.
    """
    global _client, _database
    settings = get_settings()

    logger.info("connecting_to_mongodb", uri=settings.mongodb_uri, db=settings.mongodb_db_name)

    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,  # fail fast if MongoDB is unreachable
        maxPoolSize=10,                 # max concurrent connections
        minPoolSize=2,                  # keep-alive connections
    )

    # Verify the connection is actually reachable
    await _client.admin.command("ping")

    _database = _client[settings.mongodb_db_name]
    logger.info("mongodb_connected", db=settings.mongodb_db_name)


async def close_mongodb_connection() -> None:
    """Called once at app shutdown. Closes all pooled connections cleanly."""
    global _client
    if _client is not None:
        _client.close()
        logger.info("mongodb_connection_closed")


def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the active database handle.
    Raises immediately if called before startup (programming error).
    """
    if _database is None:
        raise RuntimeError(
            "Database not initialised. "
            "Ensure connect_to_mongodb() was called during app startup."
        )
    return _database