from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.client import get_database
from app.config import Settings, get_settings


def get_db() -> AsyncIOMotorDatabase:
    """Inject the MongoDB database handle into any route that needs it."""
    return get_database()


def get_app_settings() -> Settings:
    """Inject the settings object into any route that needs it."""
    return get_settings()