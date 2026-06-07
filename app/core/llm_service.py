import time
import json
import os
import litellm
from litellm import acompletion

from app.config import get_settings
from app.models.context import AssembledContext
from app.models.response import LLMResponse
from app.utils.id_generator import generate_response_id
from app.utils.logger import get_logger
from app.utils.exceptions import LLMServiceError
from datetime import datetime, timezone

logger = get_logger(__name__)
settings = get_settings()

# Tell LiteLLM where to find the Gemini key
os.environ["GEMINI_API_KEY"] = settings.gemini_api_key


def _build_context_block(context: AssembledContext) -> str:
    """
    Formats all retrieved source documents into a single readable context block.
    The LLM uses this block to ground its answer.
    """
    if not context.source_documents:
        return "No source documents provided."

    parts = []
    for i, doc in enumerate(context.source_documents, start=1):
        title = doc.metadata.get("title", f"Document {i}")
        parts.append(
            f"[SOURCE {i} | ID: {doc.source_id} | Score: {doc.score:.2f}]\n"
            f"Title: {title}\n"
            f"{doc.content.strip()}"
        )
    return "\n\n---\n\n".join(parts)


def _build_messages(context: AssembledContext) -> list[dict]:
    """
    Assembles the full message list sent to the LLM.

    Structure:
    1. System prompt (instructions + persona)
    2. Conversation history (prior turns for multi-turn support)
    3. Final user message (query + all context blocks)

    The final user message packs everything the LLM needs:
    memory context, fresh knowledge, source documents, and the query.
    """
    context_block = _build_context_block(context)

    # Build the final user turn content
    user_content_parts = []

    if context.memory_context:
        user_content_parts.append(
            f"## Relevant Memory\n{context.memory_context}"
        )

    if context.fresh_context:
        user_content_parts.append(
            f"## Fresh Knowledge\n{context.fresh_context}"
        )

    user_content_parts.append(
        f"## Source Documents\n{context_block}"
    )

    user_content_parts.append(
        f"## User Question\n{context.user_query}"
    )

    user_content_parts.append(
        """## Instructions
Answer the user question using ONLY the information in the source documents above.
- Cite sources by their ID using the format [SOURCE_ID] inline.
- If the answer is not in the sources, say "I don't have enough information to answer this."
- After your answer, output a JSON block on its own line in this exact format:
{"confidence": 0.85, "used_source_ids": ["src_001", "src_002"]}
- Confidence is your honest estimate from 0.0 to 1.0.
- used_source_ids must only contain IDs from the SOURCE blocks above."""
    )

    final_user_content = "\n\n".join(user_content_parts)

    # Assemble full message list
    messages = [{"role": "system", "content": context.system_prompt}]
    messages.extend(context.conversation_history)
    messages.append({"role": "user", "content": final_user_content})

    return messages


def _parse_llm_output(raw_text: str, source_documents) -> tuple[str, float, list[str]]:
    """
    Extracts the answer text, confidence score, and used source IDs
    from the raw LLM output.

    The LLM is instructed to append a JSON block. We split on it.
    If parsing fails, we degrade gracefully rather than crash.
    """
    answer = raw_text.strip()
    confidence = 0.5   # safe default if parsing fails
    used_source_ids = []

    # Try to find and parse the trailing JSON block
    try:
        # Find the last { ... } block in the output
        last_brace = raw_text.rfind("{")
        last_close = raw_text.rfind("}")
        if last_brace != -1 and last_close != -1 and last_close > last_brace:
            json_str = raw_text[last_brace: last_close + 1]
            parsed = json.loads(json_str)
            confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))   # clamp to [0,1]
            used_source_ids = parsed.get("used_source_ids", [])
            # Remove the JSON block from the answer text
            answer = raw_text[:last_brace].strip()
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("llm_output_json_parse_failed", error=str(e))
        # Fall through with defaults — answer stays as full raw_text

    # Validate that returned source IDs actually exist in our documents
    valid_ids = {doc.source_id for doc in source_documents}
    used_source_ids = [sid for sid in used_source_ids if sid in valid_ids]

    return answer, confidence, used_source_ids


async def generate_response(context: AssembledContext) -> LLMResponse:
    """
    Main entry point for the LLM service.

    Takes an AssembledContext, calls the LLM, parses the output,
    and returns a structured LLMResponse.

    Raises LLMServiceError on any LLM API failure.
    """
    response_id = generate_response_id()
    messages = _build_messages(context)
    max_tokens = context.max_tokens or settings.llm_max_tokens

    logger.info(
        "llm_call_starting",
        response_id=response_id,
        session_id=context.session_id,
        model=settings.llm_model,
        num_sources=len(context.source_documents),
        num_history_turns=len(context.conversation_history),
    )

    start_time = time.monotonic()

    try:
        response = await acompletion(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=max_tokens,
        )
    except litellm.exceptions.AuthenticationError as e:
        raise LLMServiceError(
            "Gemini API key is invalid or missing. Check GEMINI_API_KEY in your .env file.",
            original_error=e,
        )
    except litellm.exceptions.RateLimitError as e:
        raise LLMServiceError(
            "Gemini rate limit exceeded. Consider adding retry logic.",
            original_error=e,
        )
    except litellm.exceptions.ContextWindowExceededError as e:
        raise LLMServiceError(
            "Context window exceeded. Reduce the number of source documents.",
            original_error=e,
        )
    except Exception as e:
        # Development fallback: if the configured model is not available
        # return a deterministic mock response so local testing works
        msg = str(e)
        if settings.is_development and "404 models" in msg:
            logger.warning("llm_model_not_found_using_dev_fallback", error=msg)
            # Build a simple fallback response using the provided context
            answer = (
                f"Answer (dev fallback): Based on {len(context.source_documents)} source(s)."
            )
            now = datetime.now(timezone.utc)
            return LLMResponse(
                response_id=response_id,
                session_id=context.session_id,
                raw_answer=answer,
                source_ids=[doc.source_id for doc in context.source_documents],
                confidence_score=0.5,
                model_used=settings.llm_model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0.0,
                created_at=now,
            )

        raise LLMServiceError(
            f"Unexpected LLM error: {type(e).__name__}: {str(e)}",
            original_error=e,
        )

    latency_ms = (time.monotonic() - start_time) * 1000

    # Extract the raw text content
    raw_text = response.choices[0].message.content or ""

    # Parse answer, confidence, and source IDs out of the raw output
    answer, confidence, used_source_ids = _parse_llm_output(
        raw_text, context.source_documents
    )

    # Token usage from the API response
    usage = response.usage or {}
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

    llm_response = LLMResponse(
        response_id=response_id,
        session_id=context.session_id,
        raw_answer=answer,
        source_ids=used_source_ids,
        confidence_score=confidence,
        model_used=settings.llm_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=round(latency_ms, 2),
        metadata={
            "tenant_id": context.tenant_id,
            "num_sources_provided": len(context.source_documents),
            "num_sources_used": len(used_source_ids),
        },
    )

    logger.info(
        "llm_call_completed",
        response_id=response_id,
        confidence=confidence,
        latency_ms=round(latency_ms, 2),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        sources_used=len(used_source_ids),
    )

    return llm_response