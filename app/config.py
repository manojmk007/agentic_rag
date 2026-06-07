from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    gemini_api_key: str = Field(..., description="Gemini API key from Google AI Studio")
    llm_model: str = Field(default="gemini/gemini-2.5-flash")
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=128, le=8192)

    # MongoDB
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    mongodb_db_name: str = Field(default="rag_service")

    # App
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # Validation thresholds
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    citation_coverage_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached settings loader.
    lru_cache means .env is read exactly once per process lifetime.
    In tests, call get_settings.cache_clear() to reload.
    """
    return Settings()