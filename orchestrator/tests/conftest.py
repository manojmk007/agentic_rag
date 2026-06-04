"""
orchestrator/tests/conftest.py
================================
Shared pytest fixtures for the orchestrator test suite.
"""

import pytest
import os

# Override settings for test environment
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/?directConnection=true")
os.environ.setdefault("MONGODB_DATABASE", "orchestrator_test_db")
os.environ.setdefault("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
os.environ.setdefault("EMBEDDING_DIMENSION", "384")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("RISK_CONTROL_ENABLED", "true")


@pytest.fixture
def sample_chunks():
    """Sample retrieved chunks for testing."""
    return [
        {
            "id": "chunk-1",
            "text": "Photosynthesis is the process by which plants convert sunlight into energy.",
            "score": 0.92,
            "source": "biology_textbook",
            "metadata": {"source": "biology_101.pdf", "section": "Chapter 3"},
        },
        {
            "id": "chunk-2",
            "text": "Chlorophyll absorbs light primarily in the blue and red wavelengths.",
            "score": 0.85,
            "source": "biology_textbook",
            "metadata": {"source": "biology_101.pdf", "section": "Chapter 3"},
        },
        {
            "id": "chunk-3",
            "text": "The Calvin cycle fixes carbon dioxide into organic molecules.",
            "score": 0.78,
            "source": "chemistry_ref",
            "metadata": {"source": "chem_ref.pdf", "section": "Biochemistry"},
        },
    ]


@pytest.fixture
def sample_memories():
    """Sample memories for testing."""
    return [
        {
            "id": "mem-1",
            "query": "What database did we choose?",
            "answer": "We chose MongoDB for the primary data store.",
            "category": "decision",
            "score": 0.88,
            "confidence": 0.95,
            "metadata": {},
        },
    ]


@pytest.fixture
def sample_conversation_turns():
    """Sample conversation turns for testing."""
    return [
        {
            "role": "user",
            "content": "What is photosynthesis?",
            "entities": ["photosynthesis"],
            "topic": "biology",
            "timestamp": "2026-06-03T10:00:00Z",
        },
        {
            "role": "assistant",
            "content": "Photosynthesis is the process by which plants convert sunlight into chemical energy.",
            "entities": ["photosynthesis", "plants", "sunlight"],
            "topic": "biology",
            "timestamp": "2026-06-03T10:00:05Z",
        },
    ]
