import ulid
import hashlib
from datetime import datetime, timezone


def generate_response_id() -> str:
    """
    Generate a new unique response ID.
    Format: resp_<ULID>
    ULIDs are time-sortable, so the database index stays efficient.
    """
    return f"resp_{ulid.new()}"


def generate_feedback_id() -> str:
    """Generate a unique feedback event ID."""
    return f"fbk_{ulid.new()}"


def generate_signal_id() -> str:
    """Generate a unique signal ID for MemPalace entries."""
    return f"sig_{ulid.new()}"


def generate_session_id() -> str:
    """Generate a session ID when one is not provided by the caller."""
    return f"sess_{ulid.new()}"