"""
orchestrator/config/settings.py
================================
Centralized configuration using Pydantic BaseSettings.
All values loaded from environment variables / .env file.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Orchestrator-wide settings. Environment variables override defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8100
    debug: bool = False
    log_level: str = "INFO"

    # ── LLM — Gemini ─────────────────────────────────────────
    gemini_api_key: str = Field("", description="Google Gemini API key")
    gemini_model_large: str = "gemini-2.5-pro"
    gemini_model_small: str = "gemini-2.5-flash"

    # ── LLM — Groq ───────────────────────────────────────────
    groq_api_key: str = Field("", description="Groq API key")
    groq_model_large: str = "llama-3.3-70b-versatile"
    groq_model_small: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # ── Primary LLM provider ─────────────────────────────────
    llm_primary_provider: Literal["gemini", "groq"] = "groq"

    # ── MongoDB ──────────────────────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "orchestrator_db"
    mongodb_max_pool_size: int = 30

    # ── Embeddings ───────────────────────────────────────────
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dimension: int = 1024
    embedding_device: str = "cpu"

    # ── Reranking ────────────────────────────────────────────
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_device: str = "cpu"
    rerank_top_k: int = 5

    # ── Document Ingestion ───────────────────────────────────
    chunk_size: int = 300
    chunk_overlap: int = 50
    hybrid_vector_weight: float = 0.7
    parent_child_window: int = 1

    # ── Optimizations ────────────────────────────────────────
    early_abort_similarity_threshold: float = 0.60
    skip_rerank_similarity_threshold: float = 0.85
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = 300


    # ── Orchestrator — Route Thresholds ──────────────────────
    conversation_confidence_threshold: float = 0.90
    memory_confidence_threshold: float = 0.90
    document_confidence_threshold: float = 0.50
    fresh_data_confidence_threshold: float = 0.70

    # ── Orchestrator — Retrieval Budget ──────────────────────
    retrieval_budget_low_top_k: int = 20
    retrieval_budget_medium_top_k: int = 50
    retrieval_budget_high_top_k: int = 100

    # ── Orchestrator — Self Correction ───────────────────────
    max_self_correction_retries: int = 2

    # ── Orchestrator — Context Quality ───────────────────────
    context_quality_min_relevance: float = 0.50
    context_quality_min_coverage: float = 0.30

    # ── Orchestrator — Conversation ──────────────────────────
    max_conversation_turns: int = 20
    conversation_full_turns: int = 5
    conversation_ttl_seconds: int = 3600

    # ── Orchestrator — Context Assembly ──────────────────────
    max_context_tokens: int = 8000

    # ── Orchestrator — Risk Control ──────────────────────────
    risk_control_enabled: bool = True

    # ── Memory Store ─────────────────────────────────────────
    memory_cache_threshold: float = 0.92
    memory_min_threshold: float = 0.70
    memory_max_results: int = 5

    @field_validator("embedding_device", mode="before")
    @classmethod
    def auto_detect_device(cls, v: str) -> str:
        if v == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    return "cpu"
            except ImportError:
                return "cpu"
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
