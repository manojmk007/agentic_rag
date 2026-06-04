"""
orchestrator/services/conversation_store.py
=============================================
MongoDB-backed conversation history persistence.

Design:
  - Tracks up to 20 turns per session.
  - Keeps last 5 turns in full.
  - Older turns are LLM-summarized and stored as a compressed summary.
  - TTL-based auto-expiry via MongoDB TTL index.
"""

from datetime import datetime, timezone
from typing import Optional

from orchestrator.config.settings import settings
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class ConversationStore:
    """Manages per-session conversation history in MongoDB."""

    @track_latency("conversation_add_turn")
    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        entities: list[str] = None,
        topic: str = "general",
    ) -> None:
        """Append a conversation turn to the session history."""
        now = datetime.now(timezone.utc)
        turn = {
            "role": role,
            "content": content,
            "entities": entities or [],
            "topic": topic,
            "timestamp": now.isoformat(),
        }

        collection = mongodb_service.conversations
        await collection.update_one(
            {"session_id": session_id},
            {
                "$push": {
                    "turns": {
                        "$each": [turn],
                        "$slice": -settings.max_conversation_turns,
                    }
                },
                "$set": {"updated_at": now},
                "$setOnInsert": {"created_at": now, "session_id": session_id},
            },
            upsert=True,
        )

    @track_latency("conversation_get_history")
    async def get_history(
        self, session_id: str, limit: Optional[int] = None
    ) -> list[dict]:
        """
        Retrieve conversation turns for a session.
        Returns up to `limit` most recent turns.
        """
        limit = limit or settings.max_conversation_turns
        collection = mongodb_service.conversations
        doc = await collection.find_one({"session_id": session_id})
        if not doc or "turns" not in doc:
            return []
        turns = doc["turns"]
        return turns[-limit:]

    async def get_recent_and_summary(
        self, session_id: str
    ) -> tuple[list[dict], str]:
        """
        Get the last N full turns + a summary of older turns.
        Returns (recent_turns, summary_text).
        """
        all_turns = await self.get_history(session_id)
        full_count = settings.conversation_full_turns

        if len(all_turns) <= full_count:
            return all_turns, ""

        recent = all_turns[-full_count:]
        older = all_turns[:-full_count]

        # Get or generate summary of older turns
        summary = await self._get_summary(session_id, older)
        return recent, summary

    async def _get_summary(
        self, session_id: str, older_turns: list[dict]
    ) -> str:
        """Get cached summary or generate a new one from older turns."""
        collection = mongodb_service.conversations
        doc = await collection.find_one(
            {"session_id": session_id},
            {"summary": 1, "summary_turn_count": 1},
        )

        cached_count = (doc or {}).get("summary_turn_count", 0)

        # If summary is up to date, return it
        if doc and doc.get("summary") and cached_count == len(older_turns):
            return doc["summary"]

        # Generate new summary
        if not older_turns:
            return ""

        summary = self._build_summary_text(older_turns)

        # Try LLM compression if available
        try:
            from orchestrator.services.llm_service import llm_service
            prompt = (
                "Compress these conversation turns into concise bullet points. "
                "Keep all facts, decisions, and entities. Remove filler:\n\n"
                f"{summary}\n\nReturn ONLY bullet points."
            )
            compressed = await llm_service.generate_simple(prompt, is_complex=False)
            summary = compressed.strip() if compressed.strip() else summary
        except Exception as e:
            logger.warning("summary_compression_failed", error=str(e))

        # Cache the summary
        await collection.update_one(
            {"session_id": session_id},
            {"$set": {"summary": summary, "summary_turn_count": len(older_turns)}},
        )
        return summary

    @staticmethod
    def _build_summary_text(turns: list[dict]) -> str:
        """Build a plain-text summary from turn dicts."""
        lines = []
        for i, t in enumerate(turns, 1):
            role = t.get("role", "unknown").capitalize()
            content = t.get("content", "")[:200]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def get_last_entities(self, session_id: str) -> list[str]:
        """Get entities from the most recent turns for coreference resolution."""
        recent = await self.get_history(session_id, limit=5)
        entities = []
        for turn in reversed(recent):
            for e in turn.get("entities", []):
                if e not in entities:
                    entities.append(e)
        return entities[:20]  # cap at 20 entities

    async def get_last_topic(self, session_id: str) -> str:
        """Get the topic of the most recent turn."""
        recent = await self.get_history(session_id, limit=1)
        if recent:
            return recent[-1].get("topic", "general")
        return "general"

    async def clear_session(self, session_id: str) -> bool:
        """Delete a session's conversation history."""
        collection = mongodb_service.conversations
        result = await collection.delete_one({"session_id": session_id})
        return result.deleted_count > 0


# Module-level singleton
conversation_store = ConversationStore()
