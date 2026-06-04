"""
orchestrator/services/llm_service.py
======================================
Adaptive LLM service supporting Gemini (primary) and Groq (secondary).

Features:
  - Adaptive model selection (simple → flash/instant, complex → pro/versatile)
  - Provider fallback on error
  - generate_simple(prompt) — for utility tasks
  - generate_json(prompt, schema) — for structured extraction
"""

import asyncio
import json
import re
from typing import Optional

from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


# ── LLM Response ─────────────────────────────────────────────

class LLMResponse:
    def __init__(self, text: str, model: str, provider: str, tokens_used: int = 0):
        self.text = text
        self.model = model
        self.provider = provider
        self.tokens_used = tokens_used


# ── Gemini Client ─────────────────────────────────────────────

class GeminiClient:
    """Async wrapper around google-generativeai."""

    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        self._genai = genai

    def _get_model(self, is_complex: bool) -> str:
        return settings.gemini_model_large if is_complex else settings.gemini_model_small

    async def generate(
        self, prompt: str, system_prompt: str = "", is_complex: bool = False
    ) -> LLMResponse:
        model_name = self._get_model(is_complex)
        model = self._genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt or None,
        )
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config=self._genai.types.GenerationConfig(
                    max_output_tokens=2048,
                    temperature=0.1,
                ),
            ),
        )
        text = response.text
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            model=model_name,
            provider="gemini",
            tokens_used=(usage.total_token_count if usage else 0),
        )


# ── Groq Client ──────────────────────────────────────────────

class GroqClient:
    """Async wrapper for Groq via OpenAI-compatible API."""

    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
        )

    def _get_model(self, is_complex: bool) -> str:
        return settings.groq_model_large if is_complex else settings.groq_model_small

    async def generate(
        self, prompt: str, system_prompt: str = "", is_complex: bool = False
    ) -> LLMResponse:
        model_name = self._get_model(is_complex)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=2048,
            temperature=0.1,
        )
        text = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0
        return LLMResponse(text=text, model=model_name, provider="groq", tokens_used=tokens)


# ── Adaptive LLM Service ─────────────────────────────────────

class LLMService:
    """
    Adaptive LLM router with provider fallback.
    Routes to Gemini or Groq based on settings + complexity.
    """

    def __init__(self):
        self._gemini: Optional[GeminiClient] = None
        self._groq: Optional[GroqClient] = None
        self._llm_cache = {}

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    def _get_groq(self) -> GroqClient:
        if self._groq is None:
            self._groq = GroqClient()
        return self._groq

    def _get_primary(self, is_complex: bool = False):
        """Return (primary, fallback) client pair."""
        if is_complex and settings.gemini_api_key:
            return self._get_gemini(), self._get_groq()
        if settings.llm_primary_provider == "gemini" and settings.gemini_api_key:
            return self._get_gemini(), self._get_groq()
        return self._get_groq(), self._get_gemini()

    @track_latency("llm_generate_simple")
    async def generate_simple(
        self, prompt: str, is_complex: bool = False, system_prompt: str = ""
    ) -> str:
        """Generate a response to a raw prompt. Used for utility tasks."""
        if settings.llm_cache_enabled:
            import time
            cache_key = (prompt, is_complex, system_prompt)
            if cache_key in self._llm_cache:
                ts, cached_text = self._llm_cache[cache_key]
                if time.time() - ts < settings.llm_cache_ttl_seconds:
                    logger.info("llm_cache_hit", prompt=prompt[:60])
                    return cached_text
                else:
                    del self._llm_cache[cache_key]

        primary, fallback = self._get_primary(is_complex)
        try:
            response = await primary.generate(prompt, system_prompt, is_complex)
            text = response.text
        except Exception as e:
            logger.warning("primary_llm_failed", error=str(e))
            try:
                response = await fallback.generate(prompt, system_prompt, is_complex)
                text = response.text
            except Exception as e2:
                logger.error("all_llm_failed", error=str(e2))
                raise

        if settings.llm_cache_enabled:
            import time
            if len(self._llm_cache) >= 500:
                self._llm_cache.clear()
            self._llm_cache[(prompt, is_complex, system_prompt)] = (time.time(), text)

        return text

    @track_latency("llm_generate_json")
    async def generate_json(
        self, prompt: str, is_complex: bool = False, system_prompt: str = ""
    ) -> dict:
        """
        Generate a response and parse it as JSON.
        Handles markdown code fences and common LLM JSON formatting issues.
        """
        full_prompt = prompt + "\n\nRespond with valid JSON only. No markdown, no explanation."
        text = await self.generate_simple(full_prompt, is_complex, system_prompt)

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            # Remove closing fence
            text = re.sub(r"\n?```\s*$", "", text)

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning("json_parse_failed", raw_text=text[:200])
            # Attempt to extract JSON from the text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}


# Module-level singleton
llm_service = LLMService()
