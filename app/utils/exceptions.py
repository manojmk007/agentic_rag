from typing import Any


class LLMServiceError(Exception):
    """Raised when the LLM API call fails."""
    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class ValidationError(Exception):
    """Raised when response validation fails below threshold."""
    def __init__(self, message: str, scores: dict[str, float] | None = None):
        super().__init__(message)
        self.scores = scores or {}


class FormatterError(Exception):
    """Raised when response formatting fails."""
    pass


class FeedbackProcessingError(Exception):
    """Raised when feedback cannot be processed."""
    pass


class DatabaseError(Exception):
    """Raised when a MongoDB operation fails."""
    def __init__(self, message: str, collection: str | None = None):
        super().__init__(message)
        self.collection = collection


class MemPalaceError(Exception):
    """Raised when writing to MemPalace fails."""
    pass


class ResponseNotFoundError(Exception):
    """Raised when a response_id cannot be found in the database."""
    def __init__(self, response_id: str):
        super().__init__(f"Response not found: {response_id}")
        self.response_id = response_id